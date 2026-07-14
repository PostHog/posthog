import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { InsightLogicProps, QueryBasedInsightModel } from '~/types'

import { alertsUnsupportedReason, areAlertsSupportedForInsight, insightAlertsLogic } from '../logic/insightAlertsLogic'

export type AlertsButtonProps = LemonButtonProps & {
    insight: Partial<QueryBasedInsightModel>
    insightLogicProps: InsightLogicProps
    text: string
}

export function AlertsButton({ insight, insightLogicProps, text, ...props }: AlertsButtonProps): JSX.Element {
    const { push } = useActions(router)
    const logic = insightAlertsLogic({ insightId: insight.id!, insightLogicProps })
    const { alerts } = useValues(logic)
    const hogqlAlertsEnabled = useFeatureFlag('HOGQL_INSIGHT_ALERTS')
    const funnelAlertsEnabled = useFeatureFlag('FUNNEL_INSIGHT_ALERTS')

    const supported = areAlertsSupportedForInsight(insight.query, { hogqlAlertsEnabled, funnelAlertsEnabled })
    // Existing alerts must stay manageable even if the gating flag is later disabled —
    // they keep evaluating server-side, so the user needs a way in to edit or disable them.
    const disabledReason =
        supported || (alerts?.length ?? 0) > 0
            ? undefined
            : alertsUnsupportedReason({ hogqlAlertsEnabled, funnelAlertsEnabled }, insight.query)

    return (
        <LemonButton
            data-attr="manage-alerts-button"
            onClick={() => push(urls.insightAlerts(insight.short_id!))}
            disabledReason={disabledReason}
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
