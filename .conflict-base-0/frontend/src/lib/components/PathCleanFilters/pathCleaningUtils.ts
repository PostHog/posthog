import { PathCleaningFilter } from '~/types'

/**
 * Ensures all filters have order values, using array position as fallback
 */
export function ensureFilterOrder(filters: PathCleaningFilter[]): PathCleaningFilter[] {
    return filters.map((filter, index) => ({
        ...filter,
        order: filter.order ?? index,
    }))
}

/**
 * Updates all filter order values to match their array position
 */
export function updateFilterOrder(filters: PathCleaningFilter[]): PathCleaningFilter[] {
    return filters.map((filter, index) => ({
        ...filter,
        order: index,
    }))
}
