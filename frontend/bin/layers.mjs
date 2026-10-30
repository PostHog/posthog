// The frontend's dependency layers, lowest first. A file may statically import only from its own layer
// or a lower one, so nothing from a higher layer can reach the eager graph of a lower one.
// A higher layer is reached through a dynamic import() instead (lazyWithRetry, retryImport).
export const LAYERS = ['kernel', 'shell', 'query', 'features']

// First match wins. A path that no rule names is a feature, so new code stays off the shell's eager
// path until someone moves it down in a reviewed change.
const RULES = [
    ['kernel', /^frontend\/src\/queries\/schema\//],
    ['kernel', /\/generated\//],
    ['kernel', /^frontend\/src\/lib\/(utils|logic|lemon-ui|ui|api[a-z-]*|constants|dayjs|hooks|colors)(\/|\.|$)/],
    ['kernel', /^frontend\/src\/(types|initKea|globals)\.tsx?$/],
    ['kernel', /^frontend\/src\/(styles|vendor)\//],
    ['kernel', /^frontend\/@posthog\//],
    ['kernel', /^(common|packages)\//],
    ['query', /^frontend\/src\/queries\//],
    ['shell', /^frontend\/src\/(lib|layout|models|taxonomy)\//],
    ['shell', /^frontend\/src\/scenes\/[^/]+$/],
    ['shell', /^frontend\/src\/[^/]+$/],
]

export function layerOf(file) {
    return RULES.find(([, pattern]) => pattern.test(file))?.[0] ?? 'features'
}

export function isUpward(fromFile, toFile) {
    return LAYERS.indexOf(layerOf(toFile)) > LAYERS.indexOf(layerOf(fromFile))
}

export const shortName = (file) => file.replace(/^frontend\/src\//, '')

// Folder a report shows a file under: a product, a lib component, or a top-level folder.
export function groupOf(file) {
    const parts = shortName(file).split('/')
    if (parts[0] === 'products') {
        return parts.slice(0, 2).join('/') + (parts.includes('generated') ? '/generated' : '')
    }
    if (parts[0] === 'lib' && parts.length > 3) {
        return parts.slice(0, 3).join('/')
    }
    if (parts.length > 2) {
        return parts.slice(0, 2).join('/')
    }
    return parts.length === 2 ? `${parts[0]}/*` : 'src/*'
}
