import type { FilterDefinition } from './filterDefinition'
import type { QuickRange } from './time/timeRanges'
import { type TimeRangeController, useTimeRangeController } from './time/useTimeRangeController'
import { type FiltersController, useFiltersController } from './useFiltersController'

export type DashboardFiltersOptions = {
    /** The filter kinds viewers can add. Left out, the dashboard has no filters. */
    types?: FilterDefinition[]
    /** Offers a time range picker with these quick ranges. Left out, the dashboard has no picker. */
    time?: { ranges?: QuickRange[]; timezone?: string }
}

export function useDashboardFilters({ types, time }: DashboardFiltersOptions): {
    filters?: FiltersController
    timeRange?: TimeRangeController
} {
    const filters = useFiltersController(types ?? [])
    const timeRange = useTimeRangeController(time?.ranges, time?.timezone)
    return { filters: types ? filters : undefined, timeRange: time ? timeRange : undefined }
}
