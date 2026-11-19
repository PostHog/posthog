import { randomUUID } from 'node:crypto'
import {
    accessSync,
    chmodSync,
    constants,
    copyFileSync,
    linkSync,
    realpathSync,
    renameSync,
    rmSync,
    statSync,
    writeFileSync,
} from 'node:fs'

import { HogError } from '@/core/errors'
import type { Env } from '@/core/runtime'

import { contentHash } from './container'
import { GitError, gitInfo, type GitInfo } from './git'
import { isEmptyMapContent, isUuid, pairUpload, uuidv5, type ReleaseMode, type Skip, type SourcePair } from './kinds/js'
import { packVersion, type ReleaseFields } from './release'
import { uuidv7, type StoredData, type SymbolSetUpload } from './upload'

export type InjectAction = 'injected' | 'release_updated' | 'unchanged'

export interface InjectOutcome {
    action: InjectAction
    chunkId: string
}

// A bundler debug id becomes the chunk id when it parses as a UUID. The source comment wins over the
// map's `debugId` when both exist.
function adoptedDebugId(pair: SourcePair, warnings: string[]): string | null {
    const id = pair.debugId()
    if (id === null) {
        return null
    }
    const fromMap = pair.map.debugId
    if (pair.sourceDebugId() !== null && fromMap !== null && fromMap !== pair.sourceDebugId()) {
        warnings.push(`${pair.sourcePath}: the chunk and its sourcemap have different debug ids. Using the chunk's.`)
    }
    if (isUuid(id)) {
        return id
    }
    warnings.push(
        `${pair.sourcePath}: ignoring the malformed debug id ${JSON.stringify(id)} and deriving a chunk id from the content.`
    )
    return null
}

// Event mode: chunk ids derive from the bundle's content (UUIDv5), so they stay stable across
// rebuilds. A resolved release goes into the snippet; a changed release swaps only the snippet.
export function injectEventMode(pair: SourcePair, releaseId: string | null, warnings: string[]): InjectOutcome {
    const existing = pair.chunkId()
    if (existing === null) {
        const chunkId = adoptedDebugId(pair, warnings) ?? uuidv5(Buffer.from(pair.source, 'utf8'))
        pair.addChunkId(chunkId, releaseId)
        return { action: 'injected', chunkId }
    }
    if (releaseId === null || pair.injectedReleaseId() === releaseId) {
        return { action: 'unchanged', chunkId: existing }
    }
    pair.removeChunkId(existing)
    pair.addChunkId(existing, releaseId)
    return { action: 'release_updated', chunkId: existing }
}

export function injectSymbolSetMode(pair: SourcePair, releaseId: string | null, newId: () => string): InjectOutcome {
    const existing = pair.chunkId()
    if (pair.map.releaseId === releaseId && existing !== null) {
        return { action: 'unchanged', chunkId: existing }
    }
    pair.map.releaseId = releaseId
    const chunkId = newId()
    if (existing !== null) {
        pair.removeChunkId(existing)
    }
    pair.addChunkId(chunkId, null)
    return { action: existing === null ? 'injected' : 'release_updated', chunkId }
}

export const randomChunkId = (now: () => number) => (): string => uuidv7(now())

// Replaces a set of files so that either all of them change or none does. posthog-cli writes every
// pair only after all of them were transformed, so a failure leaves the build untouched.
//
// `add` writes the new contents next to the target, and `commit` renames every staged file into
// place. A full disk or a read-only target then fails before any target changes, instead of
// leaving a bundle injected while its map keeps the old offsets, which a rerun can't repair.
export class StagedFiles {
    private readonly staged: { temporary: string; target: string }[] = []

    add(path: string, contents: string): void {
        const target = realpathSync(path)
        // A rename would replace a read-only file, where posthog-cli's write fails.
        accessSync(target, constants.W_OK)
        const temporary = `${target}.${randomUUID()}.tmp`
        this.staged.push({ temporary, target })

        writeFileSync(temporary, contents, { flag: 'wx' })
        chmodSync(temporary, statSync(target).mode & 0o7777)
    }

    // A rename can still fail, for example on a file another Windows process holds open, so each
    // original stays reachable under a second name until every rename worked, and the files
    // already replaced get it back. Two entries can name one target, when two bundles share a
    // map: the later entry wins, and the originals return in reverse order.
    commit(): void {
        const originals: { kept: string; target: string }[] = []
        let replaced = 0
        try {
            for (const { temporary, target } of this.staged) {
                const kept = `${target}.${randomUUID()}.tmp`
                originals.push({ kept, target })
                keepOriginal(target, kept)

                renameSync(temporary, target)
                replaced++
            }
        } catch (error) {
            for (const { kept, target } of originals.slice(0, replaced).reverse()) {
                renameSync(kept, target)
            }
            removeAll(originals.slice(replaced).map(({ kept }) => kept))
            this.discard()
            throw error
        }

        removeAll(originals.map(({ kept }) => kept))
        this.staged.length = 0
    }

    discard(): void {
        removeAll(this.staged.map(({ temporary }) => temporary))
        this.staged.length = 0
    }
}

// A hard link costs no copy. Filesystems without hard links, such as FAT, get a copy instead.
function keepOriginal(target: string, kept: string): void {
    try {
        linkSync(target, kept)
    } catch {
        copyFileSync(target, kept, constants.COPYFILE_EXCL)
    }
}

function removeAll(paths: string[]): void {
    for (const path of paths) {
        rmSync(path, { force: true })
    }
}

export type PreparedPair = { skip: Skip } | { upload: SymbolSetUpload; nativeFirst: boolean }

// `keep` takes the container out of memory. The content hash is fixed here, because the upload
// can't hash a container it no longer holds.
export function preparePair(pair: SourcePair, mode: ReleaseMode, keep: (data: Uint8Array) => StoredData): PreparedPair {
    if (pair.chunkId() === null && pair.debugId() === null) {
        return {
            skip: {
                path: pair.sourcePath,
                reason: 'no PostHog chunk ID or native debug ID. Run `hog error-tracking inject` first.',
            },
        }
    }
    if (isEmptyMapContent(pair.map)) {
        return {
            skip: {
                path: pair.sourcePath,
                // Keep in step with WRAPPER_JS_SIZE_THRESHOLD_BYTES in cli/src/sourcemaps/plain/upload.rs.
                reason:
                    Buffer.byteLength(pair.source) < 4096
                        ? 'the sourcemap is empty'
                        : 'the sourcemap is empty although the file is large. Check your bundler sourcemap setting.',
            },
        }
    }

    const upload = pairUpload(pair, mode)
    return {
        upload: { ...upload, contentHash: upload.contentHash ?? contentHash(upload.data), data: keep(upload.data) },
        nativeFirst: pair.chunkId() === null && pair.sourceDebugId() !== null,
    }
}

// Bundles that carry only a native debug id go first. Of the bundles that share a chunk id, only
// the first one in that order uploads.
export function dropDuplicateChunks<T extends { upload: SymbolSetUpload; nativeFirst: boolean }>(
    prepared: T[]
): { uploads: T[]; duplicates: string[] } {
    const rank = (entry: T): number => (entry.nativeFirst ? 0 : 1)
    const sorted = prepared
        .map((entry, index) => ({ entry, index }))
        .sort((a, b) => rank(a.entry) - rank(b.entry) || a.index - b.index)
    const seen = new Set<string>()
    const duplicates: string[] = []
    const uploads = sorted
        .map(({ entry }) => entry)
        .filter((entry) => {
            if (seen.has(entry.upload.chunkId)) {
                duplicates.push(entry.upload.chunkId)
                return false
            }
            seen.add(entry.upload.chunkId)
            return true
        })
    return { uploads, duplicates }
}

export interface JsRelease {
    name: string
    version: string
    git: GitInfo | undefined
}

export function resolveJsRelease(
    fields: ReleaseFields,
    env: Env,
    cwd: string,
    warnings: string[]
): JsRelease | undefined {
    let name = fields.name
    let version = packVersion(fields.version, fields.build)
    const complete = name !== undefined && version !== undefined
    let git: GitInfo | undefined
    try {
        git = gitInfo(env, cwd)
    } catch (error) {
        if (!(error instanceof GitError)) {
            throw error
        }
        if (!complete) {
            throw new HogError(
                'git_failed',
                `hog couldn't read the git repository for the release: ${error.message}`,
                'Pass --release-name and --release-version.'
            )
        }
        warnings.push(`Skipping git metadata for the release: ${error.message}`)
    }
    if (git) {
        name ??= git.repo_name
        version ??= git.commit_id
    }
    return name !== undefined && version !== undefined ? { name, version, git } : undefined
}

export function releaseRequested(fields: ReleaseFields): boolean {
    return fields.name !== undefined || fields.version !== undefined || fields.build !== undefined
}
