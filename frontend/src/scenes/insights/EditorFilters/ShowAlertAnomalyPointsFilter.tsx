import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightLogicProps } from '~/types'

export function ShowAlertAnomalyPointsFilter(): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    // Unsaved insights can't have alerts — mounting insightAlertsLogic without an id would fire a
    // pointless alerts fetch.
    if (!insight.id) {
        return null
    }

    return <AnomalyPointsToggle insightId={insight.id} insightLogicProps={insightProps} />
}

function AnomalyPointsToggle({
    insightId,
    insightLogicProps,
}: {
    insightId: number
    insightLogicProps: InsightLogicProps
}): JSX.Element | null {
    const logic = insightAlertsLogic({ insightId, insightLogicProps })
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
