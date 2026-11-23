import { readdirSync, realpathSync, statSync } from 'node:fs'
import { isAbsolute, join, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'

import { HERMES_BUNDLE_EXTENSIONS } from './kinds/hermes'
import { hasBundleName, JS_EXTENSIONS } from './kinds/js'
import { commandWorker, type Detected } from './worker'

export interface Root {
    path: string
    kind?: ArtifactKind
    mapId?: string
    // Globs relative to `path`. Matching files are never opened.
    ignore?: string[]
}

export interface DiscoverOptions {
    // Strips a URL prefix from `sourceMappingURL` comments, so absolute URLs resolve to local maps.
    publicPathPrefix?: string
}

export interface Artifact {
    kind: ArtifactKind
    path: string
    // The path as the caller sees it, relative to the working folder.
    display: string
    root: Root
}

// Each artifact type answers whether a file belongs to it. Detection is deterministic: the same
// files always give the same result, and a file only two types could claim is an error.
interface Detector {
    kind: ArtifactKind
    // While scanning a folder, only files with these extensions are opened. Null opens every file.
    extensions: readonly string[] | null
    matches(path: string, answers: Detected): boolean
}

const DETECTORS: readonly Detector[] = [
    {
        kind: 'proguard',
        extensions: ['.txt'],
        matches: (path, answers) => answers.mapping.has(path),
    },
    {
        // A bundle counts only when its sourcemap exists, as in posthog-cli. Bundles without one are
        // skipped without a message, because most build folders hold some.
        kind: 'js',
        extensions: JS_EXTENSIONS,
        matches: (path, answers) => hasBundleName(path, JS_EXTENSIONS) && answers.sourcemap.has(path),
    },
    {
        kind: 'hermes',
        extensions: HERMES_BUNDLE_EXTENSIONS,
        matches: (path, answers) => hasBundleName(path, HERMES_BUNDLE_EXTENSIONS) && answers.sourcemap.has(path),
    },
    {
        kind: 'hermes',
        extensions: ['.map'],
        matches: (path, answers) => answers.composed.has(path),
    },
    {
        // Native binaries have any name, so their first 4 bytes decide. Upload reports the ones it
        // can't send, such as files without debug info, as posthog-cli does.
        kind: 'elf',
        extensions: null,
        matches: (path, answers) => answers.elf.has(path),
    },
    {
        kind: 'dsym',
        extensions: null,
        matches: (path, answers) => answers.macho.has(path),
    },
]

export const isDsymBundle = (path: string): boolean => path.endsWith('.dSYM')

function detect(
    path: string,
    fromFolder: boolean,
    kind: ArtifactKind | undefined,
    answers: Detected
): ArtifactKind | undefined {
    const candidates = DETECTORS.filter(
        (detector) =>
            (kind === undefined || detector.kind === kind) &&
            (!fromFolder ||
                detector.extensions === null ||
                detector.extensions.some((extension) => path.endsWith(extension)))
    )
    const matched = [
        ...new Set(candidates.filter((detector) => detector.matches(path, answers)).map((detector) => detector.kind)),
    ]
    if (matched.length > 1) {
        throw new HogError(
            'ambiguous_artifact',
            `${path} looks like more than one artifact type: ${matched.join(', ')}.`,
            'Pass --kind to say which one it is.'
        )
    }
    return matched[0]
}

// Sorted, so runs on different machines visit files in the same order. Symlinks are skipped, as
// in posthog-cli, so a link can't make hog rewrite files outside the folder. A dSYM bundle is one
// artifact, so the walk doesn't look inside it. A folder that can't be read is skipped, as in
// posthog-cli, which drops the walk errors.
function walk(folder: string, out: { files: string[]; bundles: string[] }): void {
    let entries
    try {
        entries = readdirSync(folder, { withFileTypes: true })
    } catch {
        return
    }
    for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
        if (entry.name === 'node_modules' || entry.name === '.git') {
            continue
        }
        const path = join(folder, entry.name)
        if (entry.isDirectory()) {
            if (isDsymBundle(entry.name)) {
                out.bundles.push(path)
            } else {
                walk(path, out)
            }
        } else if (entry.isFile()) {
            out.files.push(path)
        }
    }
}

function rootFiles(root: Root, cwd: string): { path: string; isFile: boolean; files: string[]; bundles: string[] } {
    const path = resolve(cwd, root.path)
    const stat = statSync(path, { throwIfNoEntry: false })
    if (!stat) {
        throw new HogError('path_not_found', `${root.path} doesn't exist.`)
    }
    if (stat.isFile()) {
        return { path, isFile: true, files: [path], bundles: [] }
    }
    if (isDsymBundle(path)) {
        return { path, isFile: false, files: [], bundles: [path] }
    }
    const found = { files: [] as string[], bundles: [] as string[] }
    walk(path, found)
    const kept = (file: string): boolean => !isIgnored(root, path, file)
    return { path, isFile: false, files: found.files.filter(kept), bundles: found.bundles.filter(kept) }
}

const compiledGlobs = new WeakMap<Root, Bun.Glob[]>()

export function isIgnored(root: Root, folder: string, file: string): boolean {
    const within = relative(folder, file)
    if (!root.ignore?.length || within.startsWith('..') || isAbsolute(within)) {
        return false
    }
    let globs = compiledGlobs.get(root)
    if (!globs) {
        globs = root.ignore.map((pattern) => new Bun.Glob(pattern))
        compiledGlobs.set(root, globs)
    }
    return globs.some((glob) => glob.match(within))
}

export function listFiles(roots: readonly Root[], cwd: string): string[] {
    return roots.flatMap((root) => rootFiles(root, cwd).files)
}

const MAP_EXTENSION = '.map'
const MAPPING_EXTENSION = '.txt'

export async function discover(
    ctx: Context,
    roots: readonly Root[],
    cwd: string,
    options: DiscoverOptions = {}
): Promise<Artifact[]> {
    const worker = commandWorker(ctx)
    const listed = roots.map((root) => rootFiles(root, cwd))
    // One request for every file, so the worker reads them in parallel. A root with a kind asks only
    // the checks of that kind, as `detect` runs only its detectors.
    const answers = await worker.detect(
        listed.flatMap(({ isFile, files }, index) => {
            const wants = (kind: ArtifactKind): boolean =>
                roots[index]!.kind === undefined || roots[index]!.kind === kind
            return files.map((path) => ({
                path,
                bundle:
                    (wants('js') && hasBundleName(path, JS_EXTENSIONS)) ||
                    (wants('hermes') && hasBundleName(path, HERMES_BUNDLE_EXTENSIONS)),
                map: wants('hermes') && (isFile || path.endsWith(MAP_EXTENSION)),
                mapping: wants('proguard') && (isFile || path.endsWith(MAPPING_EXTENSION)),
                native: wants('elf') || wants('dsym'),
            }))
        }),
        options.publicPathPrefix
    )

    const artifacts: Artifact[] = []
    // Overlapping paths, like `build build/hbc`, reach the same file twice.
    const seen = new Set<string>()
    const add = (artifact: Artifact): void => {
        const canonical = realpathSync(artifact.path)
        if (!seen.has(canonical)) {
            seen.add(canonical)
            artifacts.push(artifact)
        }
    }
    for (const [index, root] of roots.entries()) {
        const { path, isFile, files, bundles } = listed[index]!
        if (isFile) {
            const kind = detect(path, false, root.kind, answers)
            if (!kind) {
                throw new HogError(
                    'unknown_artifact',
                    root.kind
                        ? `${root.path} isn't a valid ${root.kind} artifact.`
                        : `hog couldn't tell what kind of artifact ${root.path} is.`,
                    root.kind ? undefined : 'Pass --kind to say which one it is.'
                )
            }
            add({ kind, path, display: relative(cwd, path) || path, root })
            continue
        }
        if (root.kind === undefined || root.kind === 'dsym') {
            for (const bundle of bundles) {
                add({ kind: 'dsym', path: bundle, display: relative(cwd, bundle) || bundle, root })
            }
        }
        for (const file of files) {
            const kind = detect(file, true, root.kind, answers)
            if (kind) {
                add({ kind, path: file, display: relative(cwd, file), root })
            }
        }
    }
    return artifacts
}
