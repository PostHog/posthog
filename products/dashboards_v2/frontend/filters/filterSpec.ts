import type { z } from 'zod'

import type { DashboardFilter } from '../dashboard/dashboardTypes'

export interface AddFilterMenuItem<Config = unknown> {
    label: string
    /** Builds the filter the menu adds. The dashboard gives it an id. */
    create: () => Omit<DashboardFilter<Config>, 'id'>
}

/**
 * Everything about a kind of filter except how its control renders. It is plain data with no React, so code outside
 * the browser can load it, such as `validateDashboard`.
 */
export interface FilterSpec<Config = unknown> {
    type: string
    addMenuItems: AddFilterMenuItem<Config>[]
    pickerLabel?: string
    configSchema: z.ZodType<Config>
    /**
     * Names what a filter narrows, such as a select filter's `key`. A dashboard holds one filter per field, so a second
     * one never leaves its meaning unclear. Left out, two filters are the same field when their configs are equal.
     */
    fieldOf?(config: Config): string
}

export function hasFilterOn(
    filters: Omit<DashboardFilter, 'id'>[],
    filter: Omit<DashboardFilter, 'id'>,
    types: FilterSpec[]
): boolean {
    const field = (candidate: Omit<DashboardFilter, 'id'>): string => {
        const spec = findFilterType(types, candidate.type)
        return spec?.fieldOf ? spec.fieldOf(candidate.config) : JSON.stringify(candidate.config)
    }
    return filters.some((existing) => existing.type === filter.type && field(existing) === field(filter))
}

export function findFilterType<T extends FilterSpec>(types: T[], type: string): T | undefined {
    return types.find((candidate) => candidate.type === type)
}
