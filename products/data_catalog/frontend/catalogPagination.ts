export const CATALOG_PAGE_SIZE = 20
/** The page size of a list that shares the page with other lists, so each one stays short. */
export const CATALOG_LAYER_PAGE_SIZE = 5

export function pageCountFor(total: number, pageSize: number = CATALOG_PAGE_SIZE): number {
    return Math.max(1, Math.ceil(total / pageSize))
}

export function itemsOnPage<Item>(items: Item[], page: number, pageSize: number = CATALOG_PAGE_SIZE): Item[] {
    const start = (page - 1) * pageSize
    return items.slice(start, start + pageSize)
}
