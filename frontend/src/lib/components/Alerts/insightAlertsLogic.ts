import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import {
    AlertConditionType,
    AlertDetectorsConfig,
    DetectorType,
    GoalLine,
    InsightThresholdType,
    ThresholdDetectorConfig,
} from '~/queries/schema/schema-general'
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
            insightVizDataLogic(props.insightLogicProps),
            ['showAlertThresholdLines', 'showAlertBreachPoints'],
            insightLogic(props.insightLogicProps),
            ['insight'],
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
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
    }),

    selectors({
        alertThresholdLines: [
            (s) => [s.alerts, s.showAlertThresholdLines],
            (alerts: AlertType[], showAlertThresholdLines: boolean): GoalLine[] => {
                const result = alerts.flatMap((alert) => {
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
                })
                return result
            },
        ],

        // Returns breach point configurations per alert for visualization
        alertBreachPointConfigs: [
            (s) => [s.alerts, s.showAlertBreachPoints],
            (
                alerts: AlertType[],
                showAlertBreachPoints: boolean
            ): { alertId: string; alertName: string; color: string; config: AlertDetectorsConfig | ThresholdDetectorConfig }[] => {
                if (!showAlertBreachPoints) {
                    return []
                }

                const colors = [
                    '#F44336', // red
                    '#E91E63', // pink
                    '#9C27B0', // purple
                    '#673AB7', // deep purple
                    '#3F51B5', // indigo
                    '#2196F3', // blue
                    '#FF9800', // orange
                    '#FF5722', // deep orange
                ]

                return alerts
                    .filter((alert) => alert.enabled)
                    .map((alert, index) => {
                        // Use detectors if available, otherwise fall back to legacy threshold
                        if (alert.detectors) {
                            return {
                                alertId: alert.id,
                                alertName: alert.name || `Alert ${index + 1}`,
                                color: colors[index % colors.length],
                                config: alert.detectors,
                            }
                        }

                        // Legacy threshold-based alerts - convert to detector config format
                        if (
                            alert.threshold?.configuration?.bounds &&
                            alert.condition?.type === AlertConditionType.ABSOLUTE_VALUE
                        ) {
                            const thresholdConfig: ThresholdDetectorConfig = {
                                type: DetectorType.THRESHOLD,
                                bounds: alert.threshold.configuration.bounds,
                                threshold_type: alert.threshold.configuration.type,
                            }
                            return {
                                alertId: alert.id,
                                alertName: alert.name || `Alert ${index + 1}`,
                                color: colors[index % colors.length],
                                config: thresholdConfig,
                            }
                        }

                        return null
                    })
                    .filter(Boolean) as { alertId: string; alertName: string; color: string; config: AlertDetectorsConfig | ThresholdDetectorConfig }[]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setQuery: ({ query }) => {
            if (values.alerts.length === 0 || areAlertsSupportedForInsight(query)) {
                actions.setShouldShowAlertDeletionWarning(false)
            } else {
                actions.setShouldShowAlertDeletionWarning(true)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // If the insight has an alerts property (even if empty), use it - this means the backend sent us the alerts data
        if (values.insight?.alerts && Array.isArray(values.insight.alerts)) {
            actions.loadAlertsSuccess(values.insight.alerts)
        } else {
            // No alerts property means we need to fetch from API (e.g., when viewing insight in isolation)
            actions.loadAlerts()
        }
    }),
])
