import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'

export function ShowAlertAnomalyPointsFilter(): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    const { showAlertAnomalyPointsFlag, hasDetectorAlerts } = useValues(logic)
    const { setShowAlertAnomalyPoints } = useActions(logic)

    if (!hasDetectorAlerts) {
        return null
    }

    return (
        <DisplayOptionCheckbox
            label="Show alert anomaly points"
            checked={showAlertAnomalyPointsFlag}
            onChange={() => setShowAlertAnomalyPoints(!showAlertAnomalyPointsFlag)}
        />
    )
}
