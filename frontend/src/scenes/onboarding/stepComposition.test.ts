import fs from 'fs'
import path from 'path'

/**
 * Per-product install steps are composed by reusing the product-analytics steps and matching on a
 * step's display title, e.g. `paSteps.filter((step) => step.title !== 'Send events')`. Nothing ties
 * that string to the step it targets, and a miss is silent: `filter` drops nothing and `map`
 * replaces nothing, so the product quietly loses a step. This asserts every such title resolves.
 */
const ONBOARDING_DOCS = path.resolve(__dirname, '../../../../docs/onboarding')

const PRODUCT_ANALYTICS_IMPORT = /from '\.\.\/product-analytics\/([\w.-]+)'/
const TITLE_KEY = /step\.title\s*[!=]==\s*'([^']+)'/g
const TITLE_DECLARATION = /title:\s*'([^']+)'/g

const matchAll = (source: string, pattern: RegExp): string[] => [...source.matchAll(pattern)].map((m) => m[1])

const readSource = (file: string): string => fs.readFileSync(file, 'utf-8')

interface CompositionKey {
    composedFile: string
    sourceFile: string
    title: string
}

const collectCompositionKeys = (): CompositionKey[] => {
    const keys: CompositionKey[] = []

    for (const product of fs.readdirSync(ONBOARDING_DOCS)) {
        const productDir = path.join(ONBOARDING_DOCS, product)
        if (product === 'product-analytics' || !fs.statSync(productDir).isDirectory()) {
            continue
        }

        for (const file of fs.readdirSync(productDir)) {
            if (!file.endsWith('.tsx')) {
                continue
            }

            const source = readSource(path.join(productDir, file))
            const importedFrom = PRODUCT_ANALYTICS_IMPORT.exec(source)?.[1]
            if (!importedFrom) {
                continue
            }

            for (const title of new Set(matchAll(source, TITLE_KEY))) {
                keys.push({ composedFile: `${product}/${file}`, sourceFile: `${importedFrom}.tsx`, title })
            }
        }
    }

    return keys
}

const compositionKeys = collectCompositionKeys()

describe('onboarding step composition', () => {
    // Without this the suite passes vacuously if the files move or the patterns above stop matching.
    it('finds composed step files to check', () => {
        expect(compositionKeys.length).toBeGreaterThan(20)
    })

    it.each(compositionKeys.map((k) => [k.composedFile, k.title, k.sourceFile, k] as const))(
        '%s composes on a step titled "%s", which product-analytics/%s defines',
        (_composedFile, _title, _sourceFile, key) => {
            const sourcePath = path.join(ONBOARDING_DOCS, 'product-analytics', key.sourceFile)
            expect(fs.existsSync(sourcePath)).toBe(true)
            expect(matchAll(readSource(sourcePath), TITLE_DECLARATION)).toContain(key.title)
        }
    )
})
