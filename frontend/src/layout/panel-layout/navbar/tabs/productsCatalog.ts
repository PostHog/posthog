import { FileSystemImport, ProductItemCategory } from '~/queries/schema/schema-general'

import { splitPath, unescapePath } from '../../ProjectTree/utils'

export interface ProductsItemGroup {
    label: string
    items: FileSystemImport[]
}

export function productsItemName(item: FileSystemImport): string {
    return item.displayLabel || unescapePath(splitPath(item.path).pop() ?? item.path)
}

export function productMatchesSearch(item: FileSystemImport, search: string): boolean {
    const query = search.trim().toLowerCase()
    return !query || `${productsItemName(item)} ${item.path}`.toLowerCase().includes(query)
}

const compareNames = (a: string, b: string): number => a.localeCompare(b, undefined, { sensitivity: 'accent' })

// A sidebar-only category: these products keep their real category everywhere else.
export const POPULAR_CATEGORY = 'Popular'

// Matched by path, not label: 'LLM analytics' is the path of the entry shown as "AI observability".
export const POPULAR_PRODUCT_PATHS = [
    'Dashboards',
    'Product analytics',
    'Web analytics',
    'LLM analytics',
    'Session replay',
    'Replay vision',
    'Feature flags',
    'Experiments',
    'Error tracking',
    'Logs',
]

const CATEGORY_ORDER: string[] = [
    POPULAR_CATEGORY,
    ProductItemCategory.ANALYTICS,
    ProductItemCategory.AI_ENGINEERING,
    ProductItemCategory.DATA,
    ProductItemCategory.MONITORING,
    ProductItemCategory.PRODUCT_ENGINEERING,
    ProductItemCategory.MESSAGING,
    ProductItemCategory.CDP,
    ProductItemCategory.SCHEMA,
    ProductItemCategory.TOOLS,
    ProductItemCategory.UNRELEASED,
]

// Unreleased holds flag-gated previews, so a category missing from the list still sorts above it.
const categoryRank = (category: string): number => {
    const index = CATEGORY_ORDER.indexOf(category)
    return index === -1 ? CATEGORY_ORDER.length - 1.5 : index
}

const compareCategories = (a: string, b: string): number => categoryRank(a) - categoryRank(b) || compareNames(a, b)

export function groupProducts(items: FileSystemImport[], search: string): ProductsItemGroup[] {
    const groups = new Map<string, FileSystemImport[]>()
    for (const item of items) {
        if (!productMatchesSearch(item, search)) {
            continue
        }
        const category = item.category || 'Other'
        const group = groups.get(category) ?? []
        group.push(item)
        groups.set(category, group)
    }
    return [...groups.entries()]
        .sort(([a], [b]) => compareCategories(a, b))
        .map(([label, entries]) => ({
            label,
            items: entries.sort((a, b) =>
                label === POPULAR_CATEGORY
                    ? POPULAR_PRODUCT_PATHS.indexOf(a.path) - POPULAR_PRODUCT_PATHS.indexOf(b.path)
                    : compareNames(productsItemName(a), productsItemName(b))
            ),
        }))
}
