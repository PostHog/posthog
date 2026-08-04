import type { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import type { AlertType } from '../types'

interface AlertModalCommonProps {
    isOpen: boolean | undefined
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    defaultToAnomalyDetection?: boolean
    insightName?: string | null
    useAlertCheckPreview?: boolean
}

export type AlertModalProps = AlertModalCommonProps &
    (
        | {
              alert: AlertType
              alertId?: never
              insightId?: never
              insightShortId?: never
              insightLogicProps?: never
          }
        | {
              alert?: never
              alertId?: AlertType['id']
              insightId: QueryBasedInsightModel['id']
              insightShortId: InsightShortId
              insightLogicProps: InsightLogicProps
          }
    )

export interface ResolvedAlertModalProps extends AlertModalCommonProps {
    initialAlert?: AlertType
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export function resolveAlertModalProps(props: AlertModalProps): ResolvedAlertModalProps {
    if (!props.alert) {
        return props
    }

    return {
        ...props,
        initialAlert: props.alert,
        alertId: props.alert.id,
        insightId: props.alert.insight.id,
        insightShortId: props.alert.insight.short_id,
        insightLogicProps: {
            dashboardItemId: props.alert.insight.short_id,
            cachedInsight: props.alert.insight,
        },
    }
}
