import { readdirSync, readFileSync, statSync } from 'node:fs'
import { isAbsolute, join, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import { HogError } from '@/core/errors'

import { HERMES_BUNDLE_EXTENSIONS, isComposedMap } from './kinds/hermes'
import { isJsBundle, JS_EXTENSIONS } from './kinds/js'
import { isValidProguardMapping } from './kinds/proguard'

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
    // While scanning a folder, only files with these extensions are opened.
    extensions: readonly string[]
    matches(path: string, options: DiscoverOptions): boolean
}

const DETECTORS: readonly Detector[] = [
    {
        kind: 'proguard',
        extensions: ['.txt'],
        matches: (path) => isValidProguardMapping(readFileSync(path)),
    },
    {
        // A bundle counts only when its sourcemap exists, as in posthog-cli. Bundles without one are
        // skipped without a message, because most build folders hold some.
        kind: 'js',
        extensions: JS_EXTENSIONS,
        matches: (path, options) => isJsBundle(path, options.publicPathPrefix),
    },
    {
        kind: 'hermes',
        extensions: HERMES_BUNDLE_EXTENSIONS,
        matches: (path, options) => isJsBundle(path, options.publicPathPrefix, HERMES_BUNDLE_EXTENSIONS),
    },
    {
        kind: 'hermes',
        extensions: ['.map'],
        matches: isComposedMap,
    },
]

function detect(
    path: string,
    fromFolder: boolean,
    kind: ArtifactKind | undefined,
    options: DiscoverOptions
): ArtifactKind | undefined {
    const candidates = DETECTORS.filter(
        (detector) =>
            (kind === undefined || detector.kind === kind) &&
            (!fromFolder || detector.extensions.some((extension) => path.endsWith(extension)))
    )
    const matched = [
        ...new Set(candidates.filter((detector) => detector.matches(path, options)).map((detector) => detector.kind)),
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

function walk(folder: string, out: string[]): void {
    // Sorted, so runs on different machines visit files in the same order. Symlinks are skipped, as
    // in posthog-cli, so a link can't make hog rewrite files outside the folder.
    for (const entry of readdirSync(folder, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
        if (entry.name === 'node_modules' || entry.name === '.git') {
            continue
        }
        const path = join(folder, entry.name)
        if (entry.isDirectory()) {
            walk(path, out)
        } else if (entry.isFile()) {
            out.push(path)
        }
    }
}

function rootFiles(root: Root, cwd: string): { path: string; isFile: boolean; files: string[] } {
    const path = resolve(cwd, root.path)
    const stat = statSync(path, { throwIfNoEntry: false })
    if (!stat) {
        throw new HogError('path_not_found', `${root.path} doesn't exist.`)
    }
    if (stat.isFile()) {
        return { path, isFile: true, files: [path] }
    }
    const files: string[] = []
    walk(path, files)
    return { path, isFile: false, files: files.filter((file) => !isIgnored(root, path, file)) }
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

export function discover(roots: readonly Root[], cwd: string, options: DiscoverOptions = {}): Artifact[] {
    const artifacts: Artifact[] = []
    for (const root of roots) {
        const { path, isFile, files } = rootFiles(root, cwd)
        if (isFile) {
            const kind = detect(path, false, root.kind, options)
            if (!kind) {
                throw new HogError(
                    'unknown_artifact',
                    root.kind
                        ? `${root.path} isn't a valid ${root.kind} artifact.`
                        : `hog couldn't tell what kind of artifact ${root.path} is.`,
                    root.kind ? undefined : 'Pass --kind to say which one it is.'
                )
            }
            artifacts.push({ kind, path, display: relative(cwd, path) || path, root })
            continue
        }
        for (const file of files) {
            const kind = detect(file, true, root.kind, options)
            if (kind) {
                artifacts.push({ kind, path: file, display: relative(cwd, file), root })
            }
        }
    }
    return artifacts
}
