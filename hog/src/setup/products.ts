import { z } from 'zod'

import type { Context } from '@/core/context'

export const PRODUCT_IDS = [
    'product-analytics',
    'web-analytics',
    'session-replay',
    'feature-flags',
    'experiments',
    'error-tracking',
    'surveys',
    'llm-analytics',
    'mcp-analytics',
    'logs',
    'metrics',
    'tracing',
    'data-warehouse',
] as const

export type ProductId = (typeof PRODUCT_IDS)[number]

export const ProductIdSchema = z.enum(PRODUCT_IDS)

// `--products`: product ids separated by commas.
export const ProductListSchema = z.string().transform((raw, ctx) => {
    const ids = raw
        .split(',')
        .map((id) => id.trim().toLowerCase())
        .filter(Boolean)
    const unknown = ids.filter((id) => !ProductIdSchema.safeParse(id).success)

    if (ids.length === 0 || unknown.length > 0) {
        const message = unknown.length > 0 ? `There is no product named ${unknown.join(', ')}.` : 'Name a product.'
        ctx.issues.push({ code: 'custom', input: raw, message })
        return z.NEVER
    }

    return ids.flatMap((id) => ProductIdSchema.safeParse(id).data ?? [])
})

interface ProductInfo {
    label: string
    description: string
    // Keywords for `hog learn -s` when the product has no `posthog:instrument-<id>` skill.
    search: string
}

// What setup says about each product. PostHog records a product intent under the id with
// underscores, such as `session_replay`.
const PRODUCTS: Record<ProductId, ProductInfo> = {
    'product-analytics': {
        label: 'Product analytics',
        description: 'Track events and chart how people use your product.',
        search: 'product analytics events',
    },
    'web-analytics': {
        label: 'Web analytics',
        description: 'See traffic, referrers and top pages for your site.',
        search: 'web analytics',
    },
    'session-replay': {
        label: 'Session replay',
        description: 'Watch recordings of real sessions in your app.',
        search: 'session replay',
    },
    'feature-flags': {
        label: 'Feature flags',
        description: 'Turn features on for some users without a deploy.',
        search: 'feature flags',
    },
    experiments: {
        label: 'Experiments',
        description: 'Run A/B tests and see which version wins.',
        search: 'experiments',
    },
    'error-tracking': {
        label: 'Error tracking',
        description: 'Capture exceptions and see which ones affect users.',
        search: 'error tracking',
    },
    surveys: {
        label: 'Surveys',
        description: 'Ask users questions inside your app.',
        search: 'surveys',
    },
    'llm-analytics': {
        label: 'LLM analytics',
        description: 'Track LLM calls, their costs and their traces.',
        search: 'llm analytics',
    },
    'mcp-analytics': {
        label: 'MCP analytics',
        description: 'See which tools agents call on your MCP server.',
        search: 'mcp analytics',
    },
    logs: {
        label: 'Logs',
        description: "Send your app's logs to PostHog and search them.",
        search: 'logs',
    },
    metrics: {
        label: 'Metrics',
        description: 'Send metrics from your services and chart them.',
        search: 'metrics',
    },
    tracing: {
        label: 'Tracing',
        description: 'Follow requests across your services.',
        search: 'tracing',
    },
    'data-warehouse': {
        label: 'Data warehouse',
        description: 'Query data from your other tools next to your events.',
        search: 'data warehouse source',
    },
}

const INSTRUMENT_PREFIX = 'posthog:instrument-'
export const INSTALL_SKILL = `${INSTRUMENT_PREFIX}integration`

export interface Product {
    id: ProductId
    label: string
    description: string
    // The `hog learn` command for adding the product to an app.
    command: string
}

export function productLabel(id: ProductId): string {
    return PRODUCTS[id].label
}

export function productIntent(id: ProductId): string {
    return id.replaceAll('-', '_')
}

// `skills` lists the `posthog:instrument-*` skills, or is undefined when they didn't load.
// Without it, every product points to a search, which works whether or not its skill exists.
function productList(skills: readonly string[] | undefined): Product[] {
    const known = new Set(skills)

    return PRODUCT_IDS.map((id) => {
        const { label, description, search } = PRODUCTS[id]
        const skill = `${INSTRUMENT_PREFIX}${id}`
        return { id, label, description, command: known.has(skill) ? `hog learn ${skill}` : `hog learn -s "${search}"` }
    })
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

// The products the person picked come first, in the order picked.
export function chosenFirst(products: readonly Product[], chosen: readonly ProductId[]): Product[] {
    const picked = chosen.flatMap((id) => products.filter((product) => product.id === id))
    return [...picked, ...products.filter((product) => !chosen.includes(product.id))]
}
