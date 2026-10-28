import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

import type { ArtifactKind } from '@/core/config'
import { HogError } from '@/core/errors'

import { isValidProguardMapping } from './kinds/proguard'

export interface Root {
    path: string
    kind?: ArtifactKind
    mapId?: string
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
    matches(path: string): boolean
}

const DETECTORS: readonly Detector[] = [
    {
        kind: 'proguard',
        extensions: ['.txt'],
        matches: (path) => isValidProguardMapping(readFileSync(path)),
    },
]

function detect(path: string, fromFolder: boolean, kind: ArtifactKind | undefined): ArtifactKind | undefined {
    const candidates = DETECTORS.filter(
        (detector) =>
            (kind === undefined || detector.kind === kind) &&
            (!fromFolder || detector.extensions.some((extension) => path.endsWith(extension)))
    )
    const matched = candidates.filter((detector) => detector.matches(path))
    if (matched.length > 1) {
        throw new HogError(
            'ambiguous_artifact',
            `${path} looks like more than one artifact type: ${matched.map((detector) => detector.kind).join(', ')}.`,
            'Pass --kind to say which one it is.'
        )
    }
    return matched[0]?.kind
}

function walk(folder: string, out: string[]): void {
    // Sorted, so runs on different machines visit files in the same order.
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

export function discover(roots: readonly Root[], cwd: string): Artifact[] {
    const artifacts: Artifact[] = []
    for (const root of roots) {
        const path = resolve(cwd, root.path)
        const stat = statSync(path, { throwIfNoEntry: false })
        if (!stat) {
            throw new HogError('path_not_found', `${root.path} doesn't exist.`)
        }
        if (stat.isFile()) {
            const kind = detect(path, false, root.kind)
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
        const files: string[] = []
        walk(path, files)
        for (const file of files) {
            const kind = detect(file, true, root.kind)
            if (kind) {
                artifacts.push({ kind, path: file, display: relative(cwd, file), root })
            }
        }
    }
    return artifacts
}
