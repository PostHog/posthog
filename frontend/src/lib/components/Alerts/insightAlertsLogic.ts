import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { AlertConditionType, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertType } from './types'

export interface InsightAlertsLogicProps {
    insightId: number
    insightLogicProps: InsightLogicProps
}

export const areAlertsSupportedForInsight = (query?: Record<string, any> | null): boolean => {
    return !!query && isInsightVizNode(query) && isTrendsQuery(query.source) && query.source.trendsFilter !== null
}

export const insightAlertsLogic = kea<insightAlertsLogicType>([
    path(['lib', 'components', 'Alerts', 'insightAlertsLogic']),
    props({} as InsightAlertsLogicProps),
    key(({ insightId }) => `insight-${insightId}`),
    actions({
        setShouldShowAlertDeletionWarning: (show: boolean) => ({ show }),
    }),

    connect((props: InsightAlertsLogicProps) => ({
        actions: [insightVizDataLogic(props.insightLogicProps), ['setQuery']],
        values: [
            insightVizDataLogic(props.insightLogicProps), ['showAlertThresholdLines'],
            insightLogic(props.insightLogicProps), ['insight']
        ],
    })),

    loaders(({ props }) => ({
        alerts: {
            __default: [] as AlertType[],
            loadAlerts: async () => {
                const response = await api.alerts.list(props.insightId)
                return response.results
            },
        },
    })),

    reducers({
        alerts: {
            deleteAlert: (state, { alertId }) => state.filter((a) => a.id !== alertId),
        },
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
    }),

    selectors({
        effectiveAlerts: [
            (s) => [s.insight, s.alerts],
            (insight, alerts): AlertType[] => {
                // Use embedded alerts from insight if available (including empty arrays), otherwise use loaded alerts
                if (insight?.alerts && Array.isArray(insight.alerts)) {
                    return insight.alerts
                }
                return alerts
            },
        ],
        alertThresholdLines: [
            (s) => [s.effectiveAlerts, s.showAlertThresholdLines],
            (alerts: AlertType[], showAlertThresholdLines: boolean): GoalLine[] =>
                alerts.flatMap((alert) => {
                    if (
                        !showAlertThresholdLines ||
                        alert.threshold.configuration.type !== InsightThresholdType.ABSOLUTE ||
                        alert.condition.type !== AlertConditionType.ABSOLUTE_VALUE ||
                        !alert.threshold.configuration.bounds
                    ) {
                        return []
                    }

                    const bounds = alert.threshold.configuration.bounds

                    const annotations = []
                    if (bounds?.upper != null) {
                        annotations.push({
                            label: `${alert.name} Upper Threshold`,
                            value: bounds?.upper,
                        })
                    }

                    if (bounds?.lower != null) {
                        annotations.push({
                            label: `${alert.name} Lower Threshold`,
                            value: bounds?.lower,
                        })
                    }

                    return annotations
                }),
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteAlert: async ({ alertId }) => {
            await api.alerts.delete(alertId)
        },
        setQuery: ({ query }) => {
            if (values.effectiveAlerts.length === 0 || areAlertsSupportedForInsight(query)) {
                actions.setShouldShowAlertDeletionWarning(false)
            } else {
                actions.setShouldShowAlertDeletionWarning(true)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // Only load alerts if they're not already embedded in the insight data
        if (!values.insight?.alerts || !Array.isArray(values.insight.alerts)) {
            actions.loadAlerts()
        }
    }),
])
