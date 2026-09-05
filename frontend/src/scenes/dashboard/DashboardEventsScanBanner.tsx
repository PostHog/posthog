import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dashboardLogic } from './dashboardLogic'

export const DashboardEventsScanBanner = (): JSX.Element | null => {
    const { showEventsScanBanner, eventsScanWarningTileCount } = useValues(dashboardLogic)
    const { snoozeEventsScanBanner } = useActions(dashboardLogic)

    if (!showEventsScanBanner) {
        return null
    }

    const summary =
        eventsScanWarningTileCount === 1
            ? 'One SQL insight on this dashboard does not limit its event names, time range, or both.'
            : `${eventsScanWarningTileCount} SQL insights on this dashboard do not limit their event names, time ranges, or both.`

    return (
        <LemonBanner type="warning" className="mt-4 mb-2" onClose={snoozeEventsScanBanner}>
            {summary} This can make each refresh slow. Each insight is marked with a warning icon next to its name. Add
            the missing event or time limit to reduce the scan.
        </LemonBanner>
    )
}
