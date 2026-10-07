import { DataWarehouseSourceCategoryApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export type SourceCategoryFilter = DataWarehouseSourceCategoryApi | 'all' | 'self-managed'

export const ALL_SOURCES_CATEGORY = 'all'

// Not a `DataWarehouseSourceCategoryApi` value: self-managed describes who holds the data, not what
// the source is about, so a connector has both a category and this flag. The sources list already
// splits on it, and people look for the same split here.
export const SELF_MANAGED_CATEGORY = 'self-managed'

// pinned: URL search param — the sources list deep-links into the catalog with it.
export const CATEGORY_SEARCH_PARAM = 'category'

export function isSourceCategoryFilter(value: unknown): value is SourceCategoryFilter {
    return (
        value === ALL_SOURCES_CATEGORY ||
        value === SELF_MANAGED_CATEGORY ||
        Object.values(DataWarehouseSourceCategoryApi).includes(value as DataWarehouseSourceCategoryApi)
    )
}
