import fs from 'fs'
import path from 'path'

import { OnboardingComponentsContext } from './shared/OnboardingDocsContentWrapper'

/**
 * Per-product install steps are composed by reusing the product-analytics steps and matching on a
 * step's display title, e.g. `paSteps.filter((step) => step.title !== 'Send events')`. Nothing ties
 * that string to the step it targets, and a miss is silent: `filter` drops nothing and `map`
 * replaces nothing, so the product quietly loses a step, with no error and no type error.
 *
 * This runs each composition against the product-analytics steps it consumes, and asserts it still
 * changes one of them. A step the composition keeps comes through as the same object, so a step it
 * dropped or replaced is one the product-analytics array holds and the composed array does not.
 * Nothing here names a title, so the check holds however the match is written.
 */
const ONBOARDING_DOCS = path.resolve(__dirname, '../../../../docs/onboarding')
const PRODUCT_ANALYTICS = path.join(ONBOARDING_DOCS, 'product-analytics')

/**
 * Compositions that only add steps, inside a product whose other compositions transform one. They
 * carry every product-analytics step through untouched, so they have no match that can stop
 * matching. The list is asserted to be exact, so a composition that stops transforming cannot hide.
 */
const ADD_ONLY = [
    // Appends its own step instead of replacing one.
    'web-analytics/wordpress.tsx',
    // These three build on their SDK's client steps, which hold no event step for the shared session
    // replay helper to drop. The helper's filter is a no-op for them, so it cannot regress either.
    'session-replay/nextjs.tsx',
    'session-replay/nuxt.tsx',
    'session-replay/svelte.tsx',
]

const stub = (name: string): (() => null) => Object.defineProperty((): null => null, 'name', { value: name })

/** Every field is a component the steps render into, so distinct no-op components are enough. */
const ctx = {
    Steps: stub('Steps'),
    Step: stub('Step'),
    CodeBlock: stub('CodeBlock'),
    CalloutBox: stub('CalloutBox'),
    ProductScreenshot: stub('ProductScreenshot'),
    OSButton: stub('OSButton'),
    Markdown: stub('Markdown'),
    Blockquote: stub('Blockquote'),
    Tab: Object.assign(stub('Tab'), {
        Group: stub('TabGroup'),
        List: stub('TabList'),
        Panels: stub('TabPanels'),
        Panel: stub('TabPanel'),
    }),
    dedent: (strings: TemplateStringsArray | string, ...values: unknown[]): string =>
        typeof strings === 'string' ? strings : String.raw({ raw: strings }, ...values),
    // Steps pull snippets by name and render the ones they use, so serve any name asked for.
    snippets: new Proxy({} as Record<string, () => null>, {
        get: (target, key: string) => (target[key] ??= stub(key)),
        has: () => true,
    }),
} as unknown as OnboardingComponentsContext

interface Step {
    title: string
}

type StepsGetter = (ctx: OnboardingComponentsContext) => Step[]
type StepsModule = Record<string, StepsGetter>

const stepsExports = (module: StepsModule): string[] =>
    Object.keys(module).filter((key) => /^get.*Steps$/.test(key) && typeof module[key] === 'function')

const tsxFilesIn = (dir: string): string[] => fs.readdirSync(dir).filter((file) => file.endsWith('.tsx'))

/**
 * Spies on every product-analytics steps getter. A composition then reveals which one it consumes
 * by calling it, and the spy holds the exact array it received.
 */
const productAnalyticsSpies = tsxFilesIn(PRODUCT_ANALYTICS).flatMap((file) => {
    const module: StepsModule = require(path.join(PRODUCT_ANALYTICS, file))
    return stepsExports(module).map((getter) => jest.spyOn(module, getter))
})

interface Composition {
    name: string
    consumed: Step[]
    composed: Step[]
}

/**
 * The product-analytics steps a composition built on. Getters call each other, so the outermost
 * call is the one whose result the composition actually received.
 */
const consumedSteps = (): Step[] | null => {
    const calls = productAnalyticsSpies.flatMap((spy) =>
        spy.mock.results.map((result, index) => ({ order: spy.mock.invocationCallOrder[index], result }))
    )
    if (!calls.length) {
        return null
    }
    return calls.reduce((first, call) => (call.order < first.order ? call : first)).result.value as Step[]
}

const runCompositions = (file: string): Composition[] => {
    const module: StepsModule = require(path.join(ONBOARDING_DOCS, file))

    return stepsExports(module).flatMap((getter) => {
        productAnalyticsSpies.forEach((spy) => spy.mockClear())
        const composed = module[getter](ctx)
        const consumed = consumedSteps()
        return consumed ? [{ name: file, consumed, composed }] : []
    })
}

const productDirs = fs
    .readdirSync(ONBOARDING_DOCS, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !['product-analytics', 'node_modules'].includes(entry.name))

const compositions = productDirs.flatMap((product) =>
    tsxFilesIn(path.join(ONBOARDING_DOCS, product.name)).flatMap((file) => runCompositions(`${product.name}/${file}`))
)

/** Steps the composition dropped or replaced: in the array it consumed, absent from the one it returned. */
const transformed = (composition: Composition): Step[] =>
    composition.consumed.filter((step) => !composition.composed.includes(step))

const productOf = (composition: Composition): string => composition.name.split('/')[0]

/** Products where compositions transform a step, so every composition in them is expected to. */
const transformingProducts = new Set(compositions.filter((c) => transformed(c).length).map(productOf))

const expectedToTransform = compositions.filter(
    (composition) => transformingProducts.has(productOf(composition)) && !ADD_ONLY.includes(composition.name)
)

describe('onboarding step composition', () => {
    // Without this the suite passes vacuously if the files move or stop exporting a steps getter.
    it('finds compositions to check', () => {
        expect(expectedToTransform.length).toBeGreaterThan(20)
    })

    // Keeps the exemption honest both ways: a new add-only composition in a transforming product
    // fails until it is listed, and a listed one that starts transforming fails until it is removed.
    it('lists every composition that only adds steps to a transforming product', () => {
        const addOnly = compositions
            .filter((c) => transformingProducts.has(productOf(c)) && !transformed(c).length)
            .map((c) => c.name)
        expect(addOnly.sort()).toEqual([...ADD_ONLY].sort())
    })

    it.each(expectedToTransform.map((composition) => [composition.name, composition] as const))(
        '%s drops or replaces a product-analytics step',
        (_name, composition) => {
            expect(transformed(composition)).not.toHaveLength(0)
        }
    )
})
