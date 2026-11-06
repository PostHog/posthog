import { DataWarehouseSourceCategoryApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export type SourceCategoryFilter = DataWarehouseSourceCategoryApi | 'all'

export const ALL_SOURCES_CATEGORY = 'all'

// pinned: URL search param — links open the catalog on a category with it.
export const CATEGORY_SEARCH_PARAM = 'category'

export function isSourceCategoryFilter(value: unknown): value is SourceCategoryFilter {
    return (
        value === ALL_SOURCES_CATEGORY ||
        Object.values(DataWarehouseSourceCategoryApi).includes(value as DataWarehouseSourceCategoryApi)
    )
}
