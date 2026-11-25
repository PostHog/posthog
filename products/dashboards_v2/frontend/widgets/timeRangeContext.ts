import { createContext } from 'react'

import type { TimeRange } from '../dashboard/dashboardTypes'

export const DEFAULT_TIME_RANGE: TimeRange = { from: 'now-7d', to: 'now' }

/**
 * The time range of widgets that do not set their own. `DashboardV2View` provides the dashboard's range, and a host
 * that renders a widget on its own can provide one, so widgets never read the dashboard to get it.
 */
export const TimeRangeContext = createContext<TimeRange>(DEFAULT_TIME_RANGE)
