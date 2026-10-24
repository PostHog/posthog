import { dayjs, type Dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { DashboardLoadAction } from './dashboardLogic'

const REFRESH_INTERVAL_SECONDS = [900, 1800, 3600]
if (process.env.NODE_ENV === 'development') {
    REFRESH_INTERVAL_SECONDS.unshift(10)
}

export const AUTO_REFRESH_INTERVAL_OPTIONS: { label: string; value: number }[] = REFRESH_INTERVAL_SECONDS.map(
    (value) => ({ label: humanFriendlyDuration(value), value })
)

/** Why the bulk refresh is blocked, or an empty string when it is available. */
export function dashboardRefreshDisabledReason({
    itemsLoading,
    blockRefresh,
    nextAllowedDashboardRefresh,
}: {
    itemsLoading: boolean
    blockRefresh: boolean
    nextAllowedDashboardRefresh: Dayjs | null
}): string {
    return !itemsLoading &&
        blockRefresh &&
        nextAllowedDashboardRefresh &&
        dayjs(nextAllowedDashboardRefresh).isAfter(dayjs())
        ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
        : ''
}

/** Progress text for a load or refresh that is in flight, for example "Loaded 1 out of 2". */
export function dashboardRefreshProgressText(
    refreshMetrics: { completed: number; total: number },
    loadAction: DashboardLoadAction | undefined
): string {
    const isInitialLoad = loadAction === 'initial_load' || loadAction === 'initial_load_with_variables'
    if (!refreshMetrics.total) {
        return isInitialLoad ? 'Loading...' : 'Refreshing...'
    }
    return `${isInitialLoad ? 'Loaded' : 'Refreshed'} ${refreshMetrics.completed} out of ${refreshMetrics.total}`
}
