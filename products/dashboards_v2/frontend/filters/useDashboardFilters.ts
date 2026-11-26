import type { ComponentType } from 'react'

import type { QuickRange } from '../time/timeRanges'
import { type TimeRangeController, useTimeRangeController } from '../time/useTimeRangeController'
import type { FilterBarProps } from './FilterBar'
import type { FilterDefinition } from './filterDefinition'
import { type FiltersController, useFiltersController } from './useFiltersController'

export interface DashboardFiltersOptions {
    /** The filter kinds viewers can add. Left out, the dashboard has no filters. */
    types?: FilterDefinition[]
    Bar?: ComponentType<FilterBarProps>
    /** Offers a time range picker with these quick ranges. Left out, the dashboard has no picker. */
    time?: { ranges?: QuickRange[]; timezone?: string }
}

export function useDashboardFilters({ types, Bar, time }: DashboardFiltersOptions): {
    filters?: FiltersController
    timeRange?: TimeRangeController
} {
    // Both hooks always run, as hooks must; an option left out only drops its part from the result.
    const filters = useFiltersController(types ?? [], Bar)
    const timeRange = useTimeRangeController(time?.ranges, time?.timezone)
    return { filters: types ? filters : undefined, timeRange: time ? timeRange : undefined }
}
