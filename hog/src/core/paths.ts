import { isAbsolute, relative, resolve } from 'node:path'

export function absolutePath(root: string, path: string): string {
    return isAbsolute(path) ? path : resolve(root, path)
}

// The path to store in posthog.json, relative to its folder. A sibling folder stays relative, as
// posthog-cli stored it, so the file works in any checkout.
export function storedPath(root: string, path: string): string {
    const rel = relative(root, path)
    return isAbsolute(rel) ? path : rel
}
