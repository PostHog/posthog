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
            {subject} more events than needed on each refresh, which is slow. Each one is marked with a warning icon
            next to its name. Limiting the query to the events it needs, or adding a timestamp filter, makes it much
            faster.
        </LemonBanner>
    )
}
