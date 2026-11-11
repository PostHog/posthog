import type { AccountTopPage, AccountTopPagesResult } from '~/queries/schema/schema-general'

export const OTHER_PAGES_KEY = 'other'

export interface TopPagesProductOption {
    key: string
    label: string
    views: number
}

/** Products that own at least one listed page, most viewed first. Pages no product owns go last as Other pages. */
export function getTopPagesProductOptions(result: AccountTopPagesResult): TopPagesProductOption[] {
    const views = new Map<string, number>()
    for (const page of result.pages) {
        const key = page.product || OTHER_PAGES_KEY
        views.set(key, (views.get(key) ?? 0) + page.views)
    }
    return [...views.entries()]
        .map(([key, total]) => ({
            key,
            label:
                key === OTHER_PAGES_KEY
                    ? 'Other pages'
                    : (result.products.find((product) => product.key === key)?.label ?? key),
            views: total,
        }))
        .sort((a, b) => Number(a.key === OTHER_PAGES_KEY) - Number(b.key === OTHER_PAGES_KEY) || b.views - a.views)
}

export function filterTopPages(pages: AccountTopPage[], productKey: string | null): AccountTopPage[] {
    if (!productKey) {
        return pages
    }
    return pages.filter((page) => (page.product || OTHER_PAGES_KEY) === productKey)
}
