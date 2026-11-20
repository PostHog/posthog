import { basename } from 'node:path'

// What hog itself knows of JavaScript bundles: which names count as one. hog-worker reads and
// writes them.

export const JS_EXTENSIONS = ['.js', '.mjs', '.cjs'] as const

// Rust's `Path::extension` gives no extension for a file named `.js`.
export function hasBundleName(path: string, extensions: readonly string[]): boolean {
    const name = basename(path)
    return name.lastIndexOf('.') !== 0 && extensions.some((extension) => name.endsWith(extension))
}

// `intended` marks a file hog left out on purpose, such as one an ignore pattern matches, so the upload
// still counts as complete.
export type Skip = { path: string; reason: string; intended?: true }

export type ReleaseMode = 'event' | 'symbol-set'
