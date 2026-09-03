import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dashboardLogic } from './dashboardLogic'

export const DashboardEventsScanBanner = (): JSX.Element | null => {
    const { showEventsScanBanner, eventsScanWarningTileCount } = useValues(dashboardLogic)
    const { snoozeEventsScanBanner } = useActions(dashboardLogic)

    if (!showEventsScanBanner) {
        return null
    }

    const subject =
        eventsScanWarningTileCount === 1
            ? 'One SQL insight on this dashboard reads'
            : `${eventsScanWarningTileCount} SQL insights on this dashboard read`

    return (
        <LemonBanner type="warning" className="mt-4 mb-2" onClose={snoozeEventsScanBanner}>
            {subject} every event in its date range on each refresh, which is slow. Each one is marked with a warning
            icon next to its name. Filtering by event name, or adding a timestamp bound, makes them much faster.
        </LemonBanner>
    )
}
