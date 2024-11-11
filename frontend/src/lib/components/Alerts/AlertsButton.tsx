import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { areAlertsSupportedForInsight } from './insightAlertsLogic'

export type AlertsButtonProps = LemonButtonProps & {
    insight: Partial<QueryBasedInsightModel>
    text: string
}

export function AlertsButton({ insight, text, ...props }: AlertsButtonProps): JSX.Element {
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
            disabledReason={
                !areAlertsSupportedForInsight(insight.query)
                    ? 'Insights are only available for trends without breakdowns. Change the insight representation to add alerts.'
                    : undefined
            }
            {...props}
        >
            {text}
        </LemonButton>
    )
}
