import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { containsHogQLQuery, isFunnelsQuery, isInsightVizNode } from '~/queries/utils'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const hogqlAlertsEnabled = !!featureFlags[FEATURE_FLAGS.HOGQL_INSIGHT_ALERTS]
    const funnelAlertsEnabled = !!featureFlags[FEATURE_FLAGS.FUNNEL_INSIGHT_ALERTS]

    const supported = areAlertsSupportedForInsight(insight.query, { hogqlAlertsEnabled, funnelAlertsEnabled })
    const isFunnelInsight = !!insight.query && isInsightVizNode(insight.query) && isFunnelsQuery(insight.query.source)
    const disabledReason = supported
        ? undefined
        : containsHogQLQuery(insight.query)
          ? 'SQL insight alerts are not enabled for your account.'
          : isFunnelInsight
            ? 'Funnel insight alerts are not enabled for your account.'
            : 'Alerts are only available for trends, SQL, and funnel insights. Change the insight representation to add alerts.'

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
