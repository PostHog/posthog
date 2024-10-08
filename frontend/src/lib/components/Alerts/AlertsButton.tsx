import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { areAlertsSupportedForInsight } from './insightAlertsLogic'

export interface AlertsButtonProps {
    insight: Partial<QueryBasedInsightModel>
}

export function AlertsButton({ insight }: AlertsButtonProps): JSX.Element {
    const { push } = useActions(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const showAlerts = featureFlags[FEATURE_FLAGS.ALERTS]

    if (!showAlerts) {
        return <></>
    }

    return (
        <LemonButton
            data-attr="manage-alerts-button"
            onClick={() => push(urls.insightAlerts(insight.short_id!))}
            fullWidth
            disabledReason={
                !areAlertsSupportedForInsight(insight.query)
                    ? 'Insights are only available for trends without breakdowns. Change the insight representation to add alerts.'
                    : undefined
            }
        >
            Manage alerts
        </LemonButton>
    )
}
