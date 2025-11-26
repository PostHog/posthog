import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AlertConditionType, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertType, ForecastResult } from './types'

export interface ForecastBand {
    label: string
    timestamps: string[]
    lowerBounds: number[]
    upperBounds: number[]
    predictedValues: number[]
    confidenceLevel: number
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
            ['showAlertThresholdLines', 'showAlertForecastIntervals'],
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
        forecastResults: {
            __default: [] as ForecastResult[],
            loadForecastResults: async () => {
                const response = await api.forecastResults.list(props.insightId)
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
        forecastBands: [
            (s) => [s.forecastResults, s.showAlertForecastIntervals, s.alerts],
            (
                forecastResults: ForecastResult[],
                showAlertForecastIntervals: boolean,
                alerts: AlertType[]
            ): ForecastBand[] => {
                if (!showAlertForecastIntervals || forecastResults.length === 0) {
                    return []
                }

                // Group forecast results by alert_configuration and series_index
                const groupedResults = new Map<string, ForecastResult[]>()
                for (const result of forecastResults) {
                    const key = `${result.alert_configuration}-${result.series_index}-${result.breakdown_value || ''}`
                    if (!groupedResults.has(key)) {
                        groupedResults.set(key, [])
                    }
                    groupedResults.get(key)!.push(result)
                }

                const bands: ForecastBand[] = []
                for (const [key, results] of groupedResults) {
                    // Sort by timestamp
                    const sorted = results.sort(
                        (a, b) => new Date(a.forecast_timestamp).getTime() - new Date(b.forecast_timestamp).getTime()
                    )

                    // Find alert name for this configuration
                    const alertId = sorted[0].alert_configuration
                    const alert = alerts.find((a) => a.id === alertId)
                    const label = alert ? `${alert.name} Forecast` : `Forecast ${key}`

                    bands.push({
                        label,
                        timestamps: sorted.map((r) => r.forecast_timestamp),
                        lowerBounds: sorted.map((r) => r.lower_bound),
                        upperBounds: sorted.map((r) => r.upper_bound),
                        predictedValues: sorted.map((r) => r.predicted_value),
                        confidenceLevel: sorted[0].confidence_level,
                    })
                }

                return bands
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

        // Load forecast results for the insight
        actions.loadForecastResults()
    }),
])
