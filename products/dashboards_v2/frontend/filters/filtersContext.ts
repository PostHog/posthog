import { createContext } from 'react'

import type { DashboardFilter } from '../dashboard/dashboardTypes'

export interface AppliedFilter<Config = unknown, Value = unknown> {
    id: string
    type: string
    config: Config
    value: Value
}

/**
 * The filters that apply to the widgets inside it. `DashboardV2View` provides the dashboard's, and a host that renders
 * a widget on its own can provide its own, so widgets never read the dashboard to get them.
 */
export const FiltersContext = createContext<AppliedFilter[]>([])

/** The filters that have a value, in the dashboard's order. A value left over from a removed filter is dropped. */
export function appliedFilters(filters: DashboardFilter[], values: Record<string, unknown>): AppliedFilter[] {
    return filters.flatMap(({ id, type, config }) => {
        const value = values[id]
        return value === undefined ? [] : [{ id, type, config, value }]
    })
}

/** Filters with a value first, otherwise in their saved order, so what applies stays in view when a row overflows. */
export function activeFirst(filters: DashboardFilter[], values: Record<string, unknown>): DashboardFilter[] {
    return [...filters].sort((a, b) => Number(values[b.id] !== undefined) - Number(values[a.id] !== undefined))
}
