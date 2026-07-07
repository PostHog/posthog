import { useActions, useValues } from 'kea'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightLogicProps } from '~/types'

import { InsightDisplayToggle, InsightToggleVariant } from './InsightDisplayToggle'

export function ShowAlertAnomalyPointsFilter({
    variant,
}: {
    variant?: InsightToggleVariant
} = {}): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    // Unsaved insights can't have alerts — mounting insightAlertsLogic without an id would fire a
    // pointless alerts fetch.
    if (!insight.id) {
        return null
    }

    return <AnomalyPointsToggle insightId={insight.id} insightLogicProps={insightProps} variant={variant} />
}

function AnomalyPointsToggle({
    insightId,
    insightLogicProps,
    variant,
}: {
    insightId: number
    insightLogicProps: InsightLogicProps
    variant?: InsightToggleVariant
}): JSX.Element | null {
    const logic = insightAlertsLogic({ insightId, insightLogicProps })
    const { showAlertAnomalyPointsFlag, hasDetectorAlerts } = useValues(logic)
    const { setShowAlertAnomalyPoints } = useActions(logic)

    if (!hasDetectorAlerts) {
        return null
    }

    return (
        <InsightDisplayToggle
            label="Show alert anomaly points"
            onChange={() => setShowAlertAnomalyPoints(!showAlertAnomalyPointsFlag)}
            checked={showAlertAnomalyPointsFlag}
            variant={variant}
        />
    )
}
