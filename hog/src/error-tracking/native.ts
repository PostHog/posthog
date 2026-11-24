import { readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import type { Context } from '@/core/context'
import { canonical } from '@/core/paths'

import { isDsymBundle, isIgnored, type Artifact, type Root } from './discover'
import type { Skip } from './session'
import { MAX_FILE_SIZE, type SymbolSetFile } from './upload'
import { commandWorker, type NativeBinary, type NativeProblem, type PackItem, type Worker } from './worker'

const NATIVE_PROBLEMS: Record<NativeProblem, string> = {
    no_debug_info: 'it has no debug info. Build with debug info, and upload before stripping it.',
    no_build_id:
        "it has no GNU build ID, so crashes can't be matched to it. Link with `-Wl,--build-id=sha1`. Go needs `-ldflags=-B=gobuildid`.",
    missing_uuid: "it has no LC_UUID, so crashes can't be matched to it. Link without `-no_uuid`.",
    compressed_dwarf:
        "its DWARF is compressed (`__zdebug` sections), which PostHog can't read yet. Go needs `-ldflags=-compressdwarf=false` on macOS.",
    unparseable_slice: "one of its architectures can't be parsed, so hog skips that architecture.",
}

const DSYM_BINARIES = join('Contents', 'Resources', 'DWARF')

// Kernel-backed files hold no source code, but some hold secrets, like /proc/self/environ. Their
// bytes change with every process, so posthog-cli can never upload the same ones.
const VIRTUAL_FILESYSTEMS = ['/proc/', '/sys/', '/dev/']

const isVirtual = (path: string): boolean => {
    const real = canonical(path)
    return VIRTUAL_FILESYSTEMS.some((prefix) => real.startsWith(prefix))
}

// A path the DWARF names can reach the source folder through a symlink, or the folder can be one,
// so the globs match the path as written and its canonical form, and either one ignores it.
function sourceIgnored(root: Root, folder: string): (path: string) => boolean {
    const realFolder = canonical(folder)
    return (path) => isIgnored(root, folder, path) || isIgnored(root, realFolder, canonical(path))
}

interface NativeFile {
    binary: NativeBinary
    artifact: Artifact
}

// A binary and its `objcopy --only-keep-debug` companion share a debug ID. The larger file holds
// at least as much debug data, so it uploads.
function dedupeNativeFiles(
    files: NativeFile[],
    onDuplicate: (dropped: NativeFile, kept: NativeFile) => void
): NativeFile[] {
    const kept = new Map<string, NativeFile>()
    for (const file of files) {
        const existing = kept.get(file.binary.debugId)
        if (!existing) {
            kept.set(file.binary.debugId, file)
        } else if (file.binary.size > existing.binary.size) {
            kept.set(file.binary.debugId, file)
            onDuplicate(existing, file)
        } else {
            onDuplicate(file, existing)
        }
    }
    return [...kept.values()]
}

// A native file that a dSYM which fits replaces is never packed, so it has no upload.
interface Packed {
    artifact: Artifact
    chunkId: string
    upload: SymbolSetFile | null
    bundle: number | null
}

// `merge_uploads_prefer_dsym`: dSYM symbol sets that fit go first, so they win over a native file
// with the same ID, then native files, then oversized dSYMs. The first set per chunk ID stays.
function mergePreferDsym(dsyms: Packed[], natives: Packed[], onDuplicate: (dropped: Packed) => void): NativeUpload[] {
    const fits = ({ upload }: Packed): boolean => upload !== null && upload.size <= MAX_FILE_SIZE
    const ordered = [...dsyms.filter(fits), ...natives, ...dsyms.filter((dsym) => !fits(dsym))]
    const seen = new Set<string>()
    const kept: NativeUpload[] = []
    for (const entry of ordered) {
        if (seen.has(entry.chunkId)) {
            onDuplicate(entry)
            continue
        }
        if (entry.upload === null) {
            throw new Error(`hog-worker packed nothing for ${entry.chunkId}, which no dSYM replaces.`)
        }
        seen.add(entry.chunkId)
        kept.push({ artifact: entry.artifact, upload: entry.upload })
    }
    return kept
}

type DsymMember = { path: string } | { failure: string }

// Symlinks are followed, as `dwarfdump` and `lipo` follow them for posthog-cli. A file that can't
// be examined fails the bundle when the walk reaches it, so it holds its place.
function dsymMembers(bundle: string, include: (path: string) => boolean): DsymMember[] {
    if (!statSync(bundle).isDirectory()) {
        throw new Error(`${bundle} is not a directory`)
    }
    const folder = join(bundle, DSYM_BINARIES)

    const members: DsymMember[] = []
    for (const name of readdirSync(folder).sort()) {
        const path = join(folder, name)
        try {
            if (statSync(path).isFile() && include(path)) {
                members.push({ path })
            }
        } catch (error) {
            members.push({ failure: (error as Error).message })
            break
        }
    }
    return members
}

interface DsymSlice {
    id: number
    uuid: string
    // The file the slice came from. Its slices share one set of sources.
    member: string
}

interface Bundle {
    artifact: Artifact
    slices: DsymSlice[]
}

async function readBundles(worker: Worker, artifacts: Artifact[], cwd: string, skipped: Skip[]): Promise<Bundle[]> {
    const listed = artifacts.map((artifact) => {
        const folder = resolve(cwd, artifact.root.path)
        try {
            return { artifact, members: dsymMembers(artifact.path, (path) => !isIgnored(artifact.root, folder, path)) }
        } catch (error) {
            return { artifact, members: [{ failure: (error as Error).message }] }
        }
    })
    const paths = listed.flatMap(({ members }) => members.flatMap((member) => ('path' in member ? [member.path] : [])))
    const answers = await worker.dsymSlices(paths)

    const bundles: Bundle[] = []
    let answered = 0
    for (const { artifact, members } of listed) {
        const slices: DsymSlice[] = []
        let failure: string | undefined
        for (const member of members) {
            const answer = 'path' in member ? answers[answered++]! : { unreadable: member.failure }
            if ('unreadable' in answer) {
                failure ??= answer.unreadable
                continue
            }
            if ('path' in member) {
                slices.push(...answer.slices.map((slice) => ({ ...slice, member: member.path })))
            }
        }
        if (failure === undefined && slices.length === 0) {
            failure = `hog found no UUIDs in the dSYM at ${artifact.path}`
        }

        if (failure === undefined) {
            bundles.push({ artifact, slices })
        } else {
            skipped.push({ path: artifact.display, reason: `hog couldn't read the dSYM: ${failure}` })
        }
    }
    return bundles
}

interface Packable {
    artifact: Artifact
    id: number
    chunkId: string
    // What the binary reads its sources from: itself, or the dSYM file it is a slice of.
    sourceKey: string
    // The place of the dSYM bundle a slice comes from, which fails or uploads as a whole.
    bundle: number | null
}

interface SourcePlan {
    id: number
    root: Root
    folder: string
}

export interface NativeUpload {
    artifact: Artifact
    upload: SymbolSetFile
}

export async function packageNative(
    ctx: Context,
    artifacts: Artifact[],
    cwd: string,
    includeSource: boolean,
    folder: string | null,
    skipped: Skip[],
    warnings: string[]
): Promise<NativeUpload[]> {
    const worker = commandWorker(ctx)
    const loose = artifacts.filter((artifact) => !isDsymBundle(artifact.path))
    const parsed = await worker.nativeCandidates(loose.map((artifact) => artifact.path))
    const files: NativeFile[] = []
    for (const [index, artifact] of loose.entries()) {
        const answer = parsed[index]!
        if ('unparseable' in answer) {
            skipped.push({ path: artifact.display, reason: `hog couldn't parse it: ${answer.unparseable}` })
            continue
        }
        for (const candidate of answer.candidates) {
            if ('problem' in candidate) {
                skipped.push({ path: artifact.display, reason: NATIVE_PROBLEMS[candidate.problem] })
            } else {
                files.push({ binary: candidate, artifact })
            }
        }
    }

    const natives: Packable[] = dedupeNativeFiles(files, (dropped, kept) =>
        skipped.push({
            path: dropped.artifact.display,
            reason: `${kept.artifact.display} has the same debug ID and is at least as large, so hog uploads that one.`,
            intended: true,
        })
    ).map(({ binary, artifact }) => ({
        artifact,
        id: binary.id,
        chunkId: binary.debugId,
        sourceKey: `binary:${binary.id}`,
        bundle: null,
    }))

    const bundles = await readBundles(
        worker,
        artifacts.filter((artifact) => isDsymBundle(artifact.path)),
        cwd,
        skipped
    )
    const dsyms: Packable[] = bundles.flatMap(({ artifact, slices }, bundle) =>
        slices.map((slice) => ({
            artifact,
            id: slice.id,
            chunkId: slice.uuid,
            sourceKey: `member:${slice.member}`,
            bundle,
        }))
    )

    const packables = [...natives, ...dsyms]
    const plans = new Map<string, SourcePlan>()
    if (includeSource) {
        for (const { artifact, id, sourceKey } of packables) {
            if (!plans.has(sourceKey)) {
                plans.set(sourceKey, { id, root: artifact.root, folder: resolve(cwd, artifact.root.path) })
            }
        }
    }
    const found = await worker.sourcePaths([...plans.values()].map(({ id }) => id))

    const sourceLists: string[][] = []
    const listOf = new Map<string, number>()
    for (const [index, [sourceKey, plan]] of [...plans].entries()) {
        const answer = found[index]!
        if ('failed' in answer) {
            continue
        }

        const ignored = sourceIgnored(plan.root, plan.folder)
        const paths = answer.paths.filter((path) => !ignored(path) && !isVirtual(path))
        if (paths.length > 0) {
            listOf.set(sourceKey, sourceLists.length)
            sourceLists.push(paths)
        }
    }

    const items: PackItem[] = packables.map(({ id, chunkId, sourceKey, bundle }) => ({
        id,
        sources: listOf.get(sourceKey) ?? null,
        chunkId,
        bundle,
    }))
    const packed = await worker.packNative(sourceLists, items, folder, MAX_FILE_SIZE)

    for (const [index, sourceKey] of [...plans.keys()].entries()) {
        const answer = found[index]!
        if ('failed' in answer) {
            warnings.push(
                `hog couldn't read the source paths from the DWARF, so it uploads without sources: ${answer.failed}`
            )
            continue
        }
        const list = listOf.get(sourceKey)
        for (const { path, message } of list === undefined ? [] : packed.unreadable[list]!) {
            warnings.push(`hog couldn't read the source file ${path}, so it isn't bundled: ${message}`)
        }
    }

    const failedBundles = new Map<number, { artifact: Artifact; message: string }>()
    const uploads: Packed[] = []
    for (const [index, { artifact, chunkId, bundle }] of packables.entries()) {
        const container = packed.containers[index]
        if (container && 'failed' in container) {
            failedBundles.set(bundle!, { artifact, message: container.failed })
        } else if (!container) {
            uploads.push({ artifact, chunkId, upload: null, bundle })
        } else {
            const { path, ...rest } = container
            uploads.push({ artifact, chunkId, upload: { chunkId, releaseId: null, ...rest, file: path }, bundle })
        }
    }
    for (const { artifact, message } of failedBundles.values()) {
        skipped.push({ path: artifact.display, reason: `hog couldn't read the dSYM: ${message}` })
    }
    const isDsym = ({ bundle }: Packed): boolean => bundle !== null
    return mergePreferDsym(
        uploads.filter(isDsym),
        uploads.filter((upload) => !isDsym(upload)),
        (dropped) =>
            skipped.push({
                path: dropped.artifact.display,
                reason: `a dSYM bundle has the same UUID ${dropped.chunkId}, so hog uploads the bundle.`,
                intended: true,
            })
    )
}
