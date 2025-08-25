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
        refreshInsightAlerts: true,
    }),

    connect((props: InsightAlertsLogicProps) => ({
        actions: [
            insightVizDataLogic(props.insightLogicProps), ['setQuery'],
            insightLogic(props.insightLogicProps), ['loadInsight']
        ],
        values: [
            insightVizDataLogic(props.insightLogicProps), ['showAlertThresholdLines'],
            insightLogic(props.insightLogicProps), ['insight']
        ],
    })),


    reducers({
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
    }),

    selectors({
        effectiveAlerts: [
            (s) => [s.insight],
            (insight): AlertType[] => {
                // Use embedded alerts from insight data
                return insight?.alerts && Array.isArray(insight.alerts) ? insight.alerts : []
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

    listeners(({ actions, values, props }) => ({
        refreshInsightAlerts: async () => {
            // Refresh the insight data to get updated alerts
            if (values.insight?.short_id) {
                actions.loadInsight(values.insight.short_id)
            }
        },
        setQuery: ({ query }) => {
            if (values.effectiveAlerts.length === 0 || areAlertsSupportedForInsight(query)) {
                actions.setShouldShowAlertDeletionWarning(false)
            } else {
                actions.setShouldShowAlertDeletionWarning(true)
            }
        },
    })),

])
