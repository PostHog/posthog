import type { Context } from '@/core/context'

interface ProductInfo {
    // Matches the omnibus skill `posthog:instrument-<id>` when there is one.
    id: string
    label: string
    description: string
    // The ProductKey PostHog records a product intent under.
    intent: string
    // Keywords for `hog learn -s` when the product has no omnibus skill.
    search: string
}

// What the purpose question and the products step say about each product. The omnibus skills the
// library lists decide which products get `hog learn posthog:instrument-<id>`, and a new omnibus
// skill shows up without an entry here, under its own name.
const PRODUCTS: readonly ProductInfo[] = [
    {
        id: 'product-analytics',
        label: 'Product analytics',
        description: 'Track events and chart how people use your product.',
        intent: 'product_analytics',
        search: 'product analytics events',
    },
    {
        id: 'web-analytics',
        label: 'Web analytics',
        description: 'See traffic, referrers and top pages for your site.',
        intent: 'web_analytics',
        search: 'web analytics',
    },
    {
        id: 'session-replay',
        label: 'Session replay',
        description: 'Watch recordings of real sessions in your app.',
        intent: 'session_replay',
        search: 'session replay',
    },
    {
        id: 'feature-flags',
        label: 'Feature flags',
        description: 'Turn features on for some users without a deploy.',
        intent: 'feature_flags',
        search: 'feature flags',
    },
    {
        id: 'experiments',
        label: 'Experiments',
        description: 'Run A/B tests and see which version wins.',
        intent: 'experiments',
        search: 'experiments',
    },
    {
        id: 'error-tracking',
        label: 'Error tracking',
        description: 'Capture exceptions and see which ones affect users.',
        intent: 'error_tracking',
        search: 'error tracking',
    },
    {
        id: 'surveys',
        label: 'Surveys',
        description: 'Ask users questions inside your app.',
        intent: 'surveys',
        search: 'surveys',
    },
    {
        id: 'llm-analytics',
        label: 'LLM analytics',
        description: 'Track LLM calls, their costs and their traces.',
        intent: 'llm_analytics',
        search: 'llm analytics',
    },
    {
        id: 'logs',
        label: 'Logs',
        description: "Send your app's logs to PostHog and search them.",
        intent: 'logs',
        search: 'logs',
    },
    {
        id: 'metrics',
        label: 'Metrics',
        description: 'Send metrics from your services and chart them.',
        intent: 'metrics',
        search: 'metrics',
    },
    {
        id: 'tracing',
        label: 'Tracing',
        description: 'Follow requests across your services.',
        intent: 'tracing',
        search: 'tracing',
    },
    {
        id: 'data-warehouse',
        label: 'Data warehouse',
        description: 'Query data from your other tools next to your events.',
        intent: 'data_warehouse',
        search: 'data warehouse source',
    },
]

const INSTRUMENT_PREFIX = 'posthog:instrument-'
export const INSTALL_SKILL = `${INSTRUMENT_PREFIX}integration`

export interface Product {
    id: string
    label: string
    description: string | null
    intent: string | null
    command: string
}

function fromSkill(id: string): Product {
    const words = id.replaceAll('-', ' ')
    return {
        id,
        label: `${words.charAt(0).toUpperCase()}${words.slice(1)}`,
        description: null,
        intent: null,
        command: `hog learn ${INSTRUMENT_PREFIX}${id}`,
    }
}

// The product's name and intent from the table alone, so steps that only name products don't
// download the skill list.
export function knownProduct(id: string): Pick<Product, 'label' | 'intent'> {
    const known = PRODUCTS.find((product) => product.id === id)
    return known ? { label: known.label, intent: known.intent } : fromSkill(id)
}

// `skills` is the library's list of skill names, or undefined when hog couldn't load it. Without it,
// every product points to a search, which works whether or not an omnibus skill exists.
function productList(skills: readonly string[] | undefined): Product[] {
    const omnibus = new Set(
        (skills ?? [])
            .filter((name) => name.startsWith(INSTRUMENT_PREFIX) && name !== INSTALL_SKILL)
            .map((name) => name.slice(INSTRUMENT_PREFIX.length))
    )
    const known = PRODUCTS.map(
        ({ search, ...product }): Product => ({
            ...product,
            command: omnibus.has(product.id)
                ? `hog learn ${INSTRUMENT_PREFIX}${product.id}`
                : `hog learn -s "${search}"`,
        })
    )
    const added = [...omnibus].filter((id) => !PRODUCTS.some((product) => product.id === id)).map(fromSkill)
    return [...known, ...added]
}

// The skill list downloads like any `hog learn`. A failure leaves every product on a search.
export async function loadProducts(ctx: Context): Promise<Product[]> {
    try {
        const result = await (await ctx.skills()).instrumentSkills()
        return productList(result.ok ? result.value.skills : undefined)
    } catch {
        return productList(undefined)
    }
}

export function chosenFirst(products: readonly Product[], chosen: readonly string[]): Product[] {
    const picked = chosen.flatMap((id) => products.filter((product) => product.id === id))
    return [...picked, ...products.filter((product) => !chosen.includes(product.id))]
}
