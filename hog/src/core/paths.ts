import { isAbsolute, relative, resolve } from 'node:path'

export function absolutePath(root: string, path: string): string {
    return isAbsolute(path) ? path : resolve(root, path)
}

// The path to store in posthog.json: relative to its folder when the path sits inside it.
export function storedPath(root: string, path: string): string {
    const rel = relative(root, path)
    return rel.startsWith('..') || isAbsolute(rel) ? path : rel
}
