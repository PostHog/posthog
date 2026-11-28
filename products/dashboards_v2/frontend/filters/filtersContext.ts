import { createContext } from 'react'

import type { SavedFilter } from '../dashboard/document/dashboardTypes'
import { type TimeRange } from './time/timeRangeSchema'
import type { TimeRangeController } from './time/useTimeRangeController'
import type { FiltersController } from './useFiltersController'

export type AppliedFilter<Config = unknown, Value = unknown> = {
    id: string
    type: string
    config: Config
    value: Value
}

export type ActiveFilters = {
    /** Overrides each panel's own time range. Left out, every panel keeps its own. */
    time?: TimeRange
    filters: AppliedFilter[]
}

/**
 * The time range and filters that apply to the panels inside it. `DashboardView` provides the dashboard's, and a host
 * that renders a panel on its own can provide its own, so panels never read the dashboard to get them.
 */
export const FiltersContext = createContext<ActiveFilters>({ filters: [] })

/**
 * The host's filter and time range controls, so a panel can change them as well as read them. Each is left out when
 * the dashboard has none. Only panels that change filters read this, because it changes with every picked value.
 */
export const FilterControlsContext = createContext<{ filters?: FiltersController; timeRange?: TimeRangeController }>({})

/** A filter's value, read as an own property, so an id such as `constructor` never picks up an inherited one. */
export function filterValue(values: Record<string, unknown>, id: string): unknown {
    return Object.hasOwn(values, id) ? values[id] : undefined
}

/** The filters that have a value, in the dashboard's order. A value left over from a removed filter is dropped. */
export function appliedFilters(filters: SavedFilter[], values: Record<string, unknown>): AppliedFilter[] {
    return filters.flatMap(({ id, type, config }) => {
        const value = filterValue(values, id)
        return value === undefined ? [] : [{ id, type, config, value }]
    })
}

/** Filters with a value first, otherwise in their saved order, so what applies stays in view when a row overflows. */
export function activeFirst(filters: SavedFilter[], values: Record<string, unknown>): SavedFilter[] {
    return [...filters].sort(
        (a, b) => Number(filterValue(values, b.id) !== undefined) - Number(filterValue(values, a.id) !== undefined)
    )
}
