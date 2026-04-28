import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

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
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() => setShowAlertAnomalyPoints(!showAlertAnomalyPointsFlag)}
            checked={showAlertAnomalyPointsFlag}
            label={<span className="font-normal">Show alert anomaly points</span>}
            size="small"
        />
    )
}
