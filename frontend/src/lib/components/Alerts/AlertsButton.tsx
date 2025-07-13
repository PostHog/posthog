import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { InsightLogicProps, QueryBasedInsightModel } from '~/types'

import { areAlertsSupportedForInsight, insightAlertsLogic } from './insightAlertsLogic'

export type AlertsButtonProps = LemonButtonProps & {
    insight: Partial<QueryBasedInsightModel>
    insightLogicProps: InsightLogicProps
    text: string
}

export function AlertsButton({ insight, insightLogicProps, text, ...props }: AlertsButtonProps): JSX.Element {
    const { push } = useActions(router)
    const logic = insightAlertsLogic({ insightId: insight.id!, insightLogicProps })
    const { alerts } = useValues(logic)

    return (
        <LemonButton
            data-attr="manage-alerts-button"
            onClick={() => push(urls.insightAlerts(insight.short_id!))}
            disabledReason={
                !areAlertsSupportedForInsight(insight.query)
                    ? 'Alerts are only available for trends. Change the insight representation to add alerts.'
                    : undefined
            }
            {...props}
            icon={
                <IconWithCount count={alerts?.length} showZero={false}>
                    <IconBell />
                </IconWithCount>
            }
        >
            {text}
        </LemonButton>
    )
}
