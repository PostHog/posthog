import { createContext } from 'react'

import type { DashboardFilter, TimeRange } from '../dashboard/dashboardTypes'

export interface AppliedFilter<Config = unknown, Value = unknown> {
    id: string
    type: string
    config: Config
    value: Value
}

export const DEFAULT_TIME_RANGE: TimeRange = { from: 'now-7d', to: 'now' }

export interface ActiveFilters {
    time: TimeRange
    filters: AppliedFilter[]
}

/**
 * The time range and filters that apply to the widgets inside it. `DashboardView` provides the dashboard's, and a host
 * that renders a widget on its own can provide its own, so widgets never read the dashboard to get them.
 */
export const FiltersContext = createContext<ActiveFilters>({ time: DEFAULT_TIME_RANGE, filters: [] })

/** A filter's value, read as an own property, so an id such as `constructor` never picks up an inherited one. */
export function filterValue(values: Record<string, unknown>, id: string): unknown {
    return Object.hasOwn(values, id) ? values[id] : undefined
}

/** The filters that have a value, in the dashboard's order. A value left over from a removed filter is dropped. */
export function appliedFilters(filters: DashboardFilter[], values: Record<string, unknown>): AppliedFilter[] {
    return filters.flatMap(({ id, type, config }) => {
        const value = filterValue(values, id)
        return value === undefined ? [] : [{ id, type, config, value }]
    })
}

/** Filters with a value first, otherwise in their saved order, so what applies stays in view when a row overflows. */
export function activeFirst(filters: DashboardFilter[], values: Record<string, unknown>): DashboardFilter[] {
    return [...filters].sort(
        (a, b) => Number(filterValue(values, b.id) !== undefined) - Number(filterValue(values, a.id) !== undefined)
    )
}
