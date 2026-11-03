/**
 * Resolves a file the app loads by URL (a web worker or snappy_bg.wasm) to the content-hashed name
 * that the production build writes into the HTML. An unhashed URL can point at a file from another
 * build, so production code must not hard-code one. Dev, Storybook and tests have no map and use
 * the unhashed name.
 */
export function staticFileUrl(fileName: string): string {
    return `/static/${window.ESBUILD_STATIC_FILES?.[fileName] ?? fileName}`
}
