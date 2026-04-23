import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function ShowAlertAnomalyPointsFilter(): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    const { showAlertAnomalyPointsFlag, hasDetectorAlerts } = useValues(logic)
    const { setShowAlertAnomalyPoints } = useActions(logic)

    if (!hasDetectorAlerts) {
        return null
    }

    return (
        <LemonSwitch
            className="px-2 py-1"
            onChange={(checked) => setShowAlertAnomalyPoints(checked)}
            checked={showAlertAnomalyPointsFlag}
            label="Show alert anomaly points"
            fullWidth
        />
    )
}
