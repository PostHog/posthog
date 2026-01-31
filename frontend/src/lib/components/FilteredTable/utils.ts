import { PaginationManual } from '@posthog/lemon-ui'

import { objectsEqual } from 'lib/utils'

export function haveFiltersChanged<T extends { page?: number }>(
    currentFilters: T,
    responseFilters: T | null | undefined
): boolean {
    if (!responseFilters) {
        return false
    }
    return !objectsEqual({ ...responseFilters, page: undefined }, { ...currentFilters, page: undefined })
}

export function buildClientFilteredPagination({
    currentPage,
    pageSize,
    clientCount,
    apiCount,
    filtersChanged,
}: {
    currentPage: number
    pageSize: number
    clientCount: number
    apiCount: number
    filtersChanged: boolean
}): PaginationManual {
    return {
        controlled: true,
        pageSize,
        currentPage,
        entryCount: filtersChanged ? clientCount : apiCount,
    }
}
