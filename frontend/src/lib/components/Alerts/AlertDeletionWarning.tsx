import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { insightLogic } from 'scenes/insights/insightLogic'

import { alertsLogic } from './alertsLogic'

export function AlertDeletionWarning(): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    const { shouldShowAlertDeletionWarning } = useValues(
        alertsLogic({ insightShortId: insight.short_id!, insightLogicProps: insightProps })
    )

    if (!shouldShowAlertDeletionWarning || !insight.short_id) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            There are alerts set up for the insight. The selected chart type of the insight doesn't support alerts, so
            the existing alerts will be deleted when you save.
        </LemonBanner>
    )
}
