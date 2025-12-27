import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AlertConditionType, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import { getInterval, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps, IntervalType } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertCheck, AlertType } from './types'

export interface AnomalyPoint {
    index: number
    date: string | null // Date string for matching with chart data
    score: number | null
    alertId: string
    alertName: string
    seriesIndex: number
}

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
            ['showAlertThresholdLines'],
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
        currentInterval: [
            (s) => [s.insight],
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (insight: any): IntervalType | null => {
                const query = insight?.query
                if (!query) {
                    return null
                }
                // Get interval from the insight's query source
                const source = 'source' in query ? query.source : query
                return getInterval(source) ?? null
            },
        ],
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
        anomalyPoints: [
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (s: any) => [s.alerts, s.currentInterval],
            (alerts: AlertType[], currentInterval: IntervalType | null): AnomalyPoint[] => {
                const points: AnomalyPoint[] = []

                for (const alert of alerts) {
                    if (!alert.checks || alert.checks.length === 0) {
                        continue
                    }

                    // Get the latest check with triggered points that matches the current interval
                    const latestCheck = alert.checks.find((check: AlertCheck) => {
                        if (!check.triggered_points || check.triggered_points.length === 0) {
                            return false
                        }
                        // If check has an interval, only show if it matches current insight interval
                        if (check.interval && currentInterval && check.interval !== currentInterval) {
                            return false
                        }
                        return true
                    })

                    if (!latestCheck?.triggered_points) {
                        continue
                    }

                    const seriesIndex = alert.config?.series_index ?? 0
                    const scores = latestCheck.anomaly_scores ?? []
                    const dates = latestCheck.triggered_dates ?? []

                    for (let i = 0; i < latestCheck.triggered_points.length; i++) {
                        const index = latestCheck.triggered_points[i]
                        points.push({
                            index,
                            date: dates[i] ?? null,
                            score: scores[index] ?? null,
                            alertId: alert.id,
                            alertName: alert.name,
                            seriesIndex,
                        })
                    }
                }

                return points
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
