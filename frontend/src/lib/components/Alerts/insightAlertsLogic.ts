import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AlertConditionType, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import { getInterval, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps, IntervalType } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertType } from './types'

export interface AnomalyPoint {
    index: number
    date: string | null
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
            (insight: any): IntervalType | null => {
                const query = insight?.query
                if (!query) {
                    return null
                }
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
            (s: any) => [s.alerts, s.currentInterval],
            (alerts: AlertType[], currentInterval: IntervalType | null): AnomalyPoint[] => {
                const points: AnomalyPoint[] = []

                for (const alert of alerts) {
                    if (!alert.checks || alert.checks.length === 0) {
                        continue
                    }

                    // Only consider the most recent check - don't show stale anomaly data from older checks
                    const mostRecentCheck = alert.checks[0]
                    if (!mostRecentCheck?.triggered_points || mostRecentCheck.triggered_points.length === 0) {
                        continue
                    }

                    // Skip if interval doesn't match current insight interval
                    if (
                        mostRecentCheck.interval &&
                        currentInterval &&
                        mostRecentCheck.interval !== currentInterval
                    ) {
                        continue
                    }

                    const seriesIndex = alert.config?.series_index ?? 0
                    const scores = mostRecentCheck.anomaly_scores ?? []
                    const dates = mostRecentCheck.triggered_dates ?? []

                    for (let i = 0; i < mostRecentCheck.triggered_points.length; i++) {
                        const dataIndex = mostRecentCheck.triggered_points[i]
                        // Use scores[i] when scores array matches triggered_points length,
                        // otherwise use scores[dataIndex] for full-length score arrays
                        const score =
                            scores.length === 1
                                ? scores[0]
                                : scores.length === mostRecentCheck.triggered_points.length
                                  ? scores[i]
                                  : scores[dataIndex]
                        points.push({
                            index: dataIndex,
                            date: dates[i] ?? null,
                            score: score ?? null,
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
