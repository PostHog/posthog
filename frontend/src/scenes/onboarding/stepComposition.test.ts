import fs from 'fs'
import path from 'path'

/**
 * Per-product install steps are composed by reusing the product-analytics steps and matching on a
 * step's display title, e.g. `paSteps.filter((step) => step.title !== 'Send events')`. Nothing ties
 * that string to the step it targets, and a miss is silent: `filter` drops nothing and `map`
 * replaces nothing, so the product quietly loses a step. This asserts every such title resolves.
 *
 * A composition can key on a title in the file that imports the product-analytics steps, or in a
 * shared helper that receives the steps getter as an argument (session replay does the latter for
 * all of its web SDKs). Both are resolved here, and a title key that resolves to neither fails.
 */
const ONBOARDING_DOCS = path.resolve(__dirname, '../../../../docs/onboarding')
const PRODUCT_ANALYTICS_DIR = path.join(ONBOARDING_DOCS, 'product-analytics')

const TITLE_KEY = /step\.title\s*[!=]==\s*'([^']+)'/g
const TITLE_DECLARATION = /title:\s*'([^']+)'/g
const RELATIVE_IMPORT = /from '(\.[^']*)'/g

const matchAll = (source: string, pattern: RegExp): string[] => [...source.matchAll(pattern)].map((m) => m[1])

const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const entryPath = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            return entry.name === 'node_modules' ? [] : walk(entryPath)
        }
        return entry.name.endsWith('.tsx') ? [entryPath] : []
    })

const sourceFiles = walk(ONBOARDING_DOCS)
const sources = new Map(sourceFiles.map((file) => [file, fs.readFileSync(file, 'utf-8')]))
const label = (file: string): string => path.relative(ONBOARDING_DOCS, file)

/** Import targets resolved to absolute paths, extensionless — what `path.resolve` gives us. */
const importsOf = new Map(
    sourceFiles.map((file) => [
        file,
        matchAll(sources.get(file)!, RELATIVE_IMPORT).map((specifier) => path.resolve(path.dirname(file), specifier)),
    ])
)

const isProductAnalytics = (file: string): boolean => file.startsWith(PRODUCT_ANALYTICS_DIR + path.sep)

/** The files that compose: everything except product-analytics itself, which is what they compose from. */
const composingFiles = sourceFiles.filter((file) => !isProductAnalytics(file))

const productAnalyticsImportsOf = (file: string): string[] =>
    importsOf.get(file)!.filter((target) => isProductAnalytics(`${target}.tsx`))

const importersOf = (file: string): string[] =>
    composingFiles.filter((candidate) => importsOf.get(candidate)!.includes(file.replace(/\.tsx$/, '')))

interface CompositionKey {
    /** The file whose onboarding breaks when the title stops resolving. */
    composedFile: string
    /** Set when the title is keyed on in a shared helper rather than in `composedFile` itself. */
    via: string | null
    title: string
    sourceFile: string
}

/**
 * Where a file keying on titles gets its product-analytics steps from: its own import, or — for a
 * shared helper taking the getter as an argument — the imports of each file that calls it.
 */
const resolveSources = (file: string): Pick<CompositionKey, 'composedFile' | 'via' | 'sourceFile'>[] => {
    const own = productAnalyticsImportsOf(file)
    if (own.length) {
        return own.map((sourceFile) => ({ composedFile: label(file), via: null, sourceFile }))
    }
    return importersOf(file).flatMap((caller) =>
        productAnalyticsImportsOf(caller).map((sourceFile) => ({
            composedFile: label(caller),
            via: label(file),
            sourceFile,
        }))
    )
}

const filesKeyingOnTitles = composingFiles.filter((file) => matchAll(sources.get(file)!, TITLE_KEY).length > 0)

const compositionKeys: CompositionKey[] = filesKeyingOnTitles.flatMap((file) =>
    [...new Set(matchAll(sources.get(file)!, TITLE_KEY))].flatMap((title) =>
        resolveSources(file).map((resolved) => ({ ...resolved, title }))
    )
)

describe('onboarding step composition', () => {
    // Without this the suite passes vacuously if the files move or the patterns above stop matching.
    it('finds composed step files to check', () => {
        expect(compositionKeys.length).toBeGreaterThan(20)
    })

    // A file keying on a title that resolves to no source is a composition this suite cannot check,
    // which is the silent gap it exists to close — a new shared helper with no caller reaching
    // product-analytics lands here rather than passing by producing nothing.
    it('resolves a product-analytics source for every file keying on a step title', () => {
        const unresolved = filesKeyingOnTitles.filter((file) => !resolveSources(file).length).map(label)
        expect(unresolved).toEqual([])
    })

    // resolveSources takes every product-analytics import, so a second one is checked rather than
    // ignored — but it would mean one of the two sources does not declare the title, so flag it.
    it('imports product-analytics steps from a single file', () => {
        const multiple = composingFiles.filter((file) => productAnalyticsImportsOf(file).length > 1).map(label)
        expect(multiple).toEqual([])
    })

    it.each(
        compositionKeys.map(
            (key) =>
                [
                    key.via ? `${key.composedFile} (via ${key.via})` : key.composedFile,
                    key.title,
                    label(`${key.sourceFile}.tsx`),
                    key,
                ] as const
        )
    )('%s composes on a step titled "%s", which %s defines', (_composedFile, _title, _sourceFile, key) => {
        const sourcePath = `${key.sourceFile}.tsx`
        expect(fs.existsSync(sourcePath)).toBe(true)
        expect(matchAll(fs.readFileSync(sourcePath, 'utf-8'), TITLE_DECLARATION)).toContain(key.title)
    })
})
