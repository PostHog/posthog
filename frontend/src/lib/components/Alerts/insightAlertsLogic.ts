import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AlertConditionType, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertType, AnomalyPoint } from './types'

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
        upsertAlert: (alert: AlertType) => ({ alert }),
        removeAlert: (alertId: AlertType['id']) => ({ alertId }),
        setSimulationAnomalyPoints: (points: AnomalyPoint[]) => ({ points }),
        clearSimulationAnomalyPoints: true,
        setShowAlertAnomalyPoints: (show: boolean) => ({ show }),
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
        alerts: [
            [] as AlertType[],
            {
                upsertAlert: (state, { alert }) => {
                    const index = state.findIndex((a) => a.id === alert.id)
                    if (index >= 0) {
                        return [...state.slice(0, index), alert, ...state.slice(index + 1)]
                    }
                    return [...state, alert]
                },
                removeAlert: (state, { alertId }) => state.filter((a) => a.id !== alertId),
            },
        ],
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
        simulationAnomalyPoints: [
            [] as AnomalyPoint[],
            {
                setSimulationAnomalyPoints: (_, { points }) => points,
                clearSimulationAnomalyPoints: () => [],
            },
        ],
        showAlertAnomalyPointsFlag: [
            false,
            {
                setShowAlertAnomalyPoints: (_, { show }) => show,
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
        /** Whether the insight has any detector-based alerts (used to show/hide the toggle). */
        hasDetectorAlerts: [
            (s) => [s.alerts],
            (alerts: AlertType[]): boolean => alerts.some((a) => !!a.detector_config),
        ],
        /** Anomaly points from the latest check of detector-based alerts, merged with any active simulation points. */
        alertAnomalyPoints: [
            (s) => [s.alerts, s.showAlertAnomalyPointsFlag, s.simulationAnomalyPoints],
            (alerts: AlertType[], showFlag: boolean, simulationPoints: AnomalyPoint[]): AnomalyPoint[] => {
                // Simulation points take priority when active (user is previewing)
                if (simulationPoints.length > 0) {
                    return simulationPoints
                }

                if (!showFlag) {
                    return []
                }

                // Derive from all firing checks of each detector-based alert.
                // Each check typically has 0-1 triggered points, so we aggregate
                // across checks to build the full anomaly timeline. Deduplicate by date.
                const seen = new Set<string>()
                return alerts.flatMap((alert) => {
                    if (!alert.detector_config || !alert.checks?.length) {
                        return []
                    }
                    const seriesIndex = alert.config?.series_index ?? 0
                    return alert.checks.flatMap((check) => {
                        if (!check.triggered_dates?.length) {
                            return []
                        }
                        return check.triggered_dates
                            .filter((date) => {
                                const key = `${seriesIndex}:${date}`
                                if (seen.has(key)) {
                                    return false
                                }
                                seen.add(key)
                                return true
                            })
                            .map((date, i) => {
                                const ptIdx = check.triggered_points?.[i] ?? 0
                                const scores = check.anomaly_scores
                                // Score array may be shorter than the point index (e.g. detect() returns single score)
                                const score =
                                    scores && ptIdx < scores.length
                                        ? scores[ptIdx]
                                        : (scores?.[scores.length - 1] ?? null)
                                return { index: ptIdx, date, score, seriesIndex }
                            })
                    })
                })
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
        setShowAlertAnomalyPoints: ({ show }) => {
            // When toggling on, reload alerts from the API to get latest check data
            // (inline alerts from the insight endpoint don't include checks)
            if (show && values.alerts.some((a) => !!a.detector_config && !a.checks?.length)) {
                actions.loadAlerts()
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
