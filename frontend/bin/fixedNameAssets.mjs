// The deploy's CDN upload treats only a path that matches this pattern as immutable. It overwrites every other
// file in place, so a long-open tab that loads code by a fixed name can get a newer file than its own JS.
export const CONTENT_HASHED_PATH = /.*\/[A-Za-z0-9][A-Za-z0-9._-]*-[A-Z0-9]{6,}\.[a-z0-9]+(\.map)?$/

const CODE_EXTENSIONS = ['.js', '.mjs', '.wasm']

export function isFixedNameCode(distPath) {
    if (!CODE_EXTENSIONS.some((extension) => distPath.endsWith(extension))) {
        return false
    }
    return !CONTENT_HASHED_PATH.test(`/${distPath}`)
}

function entryCovers(entry, distPath) {
    if (entry.endsWith('/')) {
        return distPath.startsWith(entry)
    }
    return distPath === entry
}

// `distPaths` are relative to dist/ and use forward slashes.
export function checkFixedNameFiles(distPaths, allowlistEntries) {
    const fixedNamePaths = distPaths.filter(isFixedNameCode).sort()
    const unlisted = fixedNamePaths.filter(
        (distPath) => !allowlistEntries.some((entry) => entryCovers(entry, distPath))
    )
    const stale = allowlistEntries.filter((entry) => !fixedNamePaths.some((distPath) => entryCovers(entry, distPath)))
    return { fixedNamePaths, unlisted, stale }
}
