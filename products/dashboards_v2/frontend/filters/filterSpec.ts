import type { z } from 'zod'

import type { DashboardFilter, SavedFilter } from '../dashboard/document/dashboardTypes'

export type AddFilterOption<Config = unknown> = {
    label: string
    create: () => Omit<DashboardFilter<Config>, 'id'>
}

/**
 * Everything about a kind of filter except how its control renders. It is plain data with no React, so code outside
 * the browser can load it, such as `validateDashboard`.
 */
export type FilterSpec<Config = unknown> = {
    type: string
    addFilterOptions: AddFilterOption<Config>[]
    pickerLabel?: string
    configSchema: z.ZodType<Config>
    /**
     * Names what a filter narrows, such as a select filter's `key`. A dashboard holds one filter per field, so a second
     * one never leaves its meaning unclear. Left out, two filters are the same field when their configs are equal.
     */
    fieldOf?(config: Config): string
}

export function hasFilterOn(
    filters: Omit<SavedFilter, 'id'>[],
    filter: Omit<SavedFilter, 'id'>,
    types: FilterSpec[]
): boolean {
    const field = (candidate: Omit<SavedFilter, 'id'>): string => {
        const spec = findFilterType(types, candidate.type)
        return spec?.fieldOf ? spec.fieldOf(candidate.config) : JSON.stringify(candidate.config)
    }
    return filters.some((existing) => existing.type === filter.type && field(existing) === field(filter))
}

export function findFilterType<T extends FilterSpec>(types: T[], type: string): T | undefined {
    return types.find((candidate) => candidate.type === type)
}
