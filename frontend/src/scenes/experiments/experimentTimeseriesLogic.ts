import { actions, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import {
    ExperimentMetricTimeseries,
    ExperimentQueryResponse,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'

import { getVariantInterval } from './MetricsView/shared/utils'
import type { experimentTimeseriesLogicType } from './experimentTimeseriesLogicType'

export interface ProcessedTimeseriesDataPoint {
    date: string
    value: number | null
    upper_bound: number | null
    lower_bound: number | null
    hasRealData: boolean
    number_of_samples?: number
}

export interface ChartDataset {
    label: string
    data: (number | null)[]
    borderColor: string
    borderWidth: number
    borderDash?: number[]
    fill: boolean | string
    backgroundColor?: string
    tension: number
    pointRadius: number
}

export interface ProcessedChartData {
    labels: string[]
    datasets: ChartDataset[]
    processedData: ProcessedTimeseriesDataPoint[]
}

export interface ExperimentTimeseriesLogicProps {
    experimentId: number
}

export const experimentTimeseriesLogic = kea<experimentTimeseriesLogicType>([
    path(['scenes', 'experiments', 'experimentTimeseriesLogic']),
    props({} as ExperimentTimeseriesLogicProps),

    actions(() => ({
        clearTimeseries: true,
    })),

    loaders(({ props }) => ({
        timeseries: [
            null as ExperimentMetricTimeseries | null,
            {
                loadTimeseries: async ({ metricUuid }: { metricUuid: string }) => {
                    const response = await api.get(
                        `api/projects/@current/experiments/${props.experimentId}/timeseries_results/?metric_uuid=${metricUuid}`
                    )
                    return response
                },
                clearTimeseries: () => null,
            },
        ],
    })),

    selectors({
        // Extract and process timeseries data for a specific variant
        processedVariantData: [
            (s) => [s.timeseries],
            (
                timeseries: ExperimentMetricTimeseries | null
            ): ((variantKey: string) => ProcessedTimeseriesDataPoint[]) => {
                return (variantKey: string) => {
                    if (
                        !timeseries?.timeseries ||
                        (timeseries.status !== 'completed' && timeseries.status !== 'partial')
                    ) {
                        return []
                    }

                    const timeseriesData = Object.entries(timeseries.timeseries).map(([date, data]) => ({
                        date,
                        ...(data as ExperimentQueryResponse),
                    }))

                    const sortedTimeseriesData = timeseriesData.sort((a, b) => a.date.localeCompare(b.date))

                    // Extract data for the specific variant
                    const rawProcessedData = sortedTimeseriesData.map(
                        (d: { date: string } & ExperimentQueryResponse) => {
                            if (d.variant_results && d.baseline) {
                                const variant = d.variant_results.find(
                                    (v: ExperimentVariantResultFrequentist | ExperimentVariantResultBayesian) =>
                                        v.key === variantKey
                                )
                                const baseline = d.baseline

                                if (variant && baseline) {
                                    const interval = getVariantInterval(variant)
                                    const [lower, upper] = interval || [0, 0]
                                    const delta = (lower + upper) / 2

                                    return {
                                        date: d.date,
                                        value: delta,
                                        upper_bound: upper,
                                        lower_bound: lower,
                                        hasRealData: true,
                                        number_of_samples: variant.number_of_samples,
                                    }
                                }
                            }

                            // Missing data - will be forward-filled
                            return {
                                date: d.date,
                                value: null,
                                upper_bound: null,
                                lower_bound: null,
                                hasRealData: false,
                            }
                        }
                    )

                    // Forward-fill missing data with last known values
                    return rawProcessedData.map((d: ProcessedTimeseriesDataPoint, index: number) => {
                        if (d.hasRealData) {
                            return d
                        }

                        // Find the last data point with real data
                        for (let i = index - 1; i >= 0; i--) {
                            const prevPoint = rawProcessedData[i]
                            if (prevPoint.hasRealData) {
                                return {
                                    date: d.date,
                                    value: prevPoint.value,
                                    upper_bound: prevPoint.upper_bound,
                                    lower_bound: prevPoint.lower_bound,
                                    hasRealData: false,
                                    number_of_samples: prevPoint.number_of_samples,
                                }
                            }
                        }

                        // If no previous data found, use zeros
                        return {
                            date: d.date,
                            value: 0,
                            upper_bound: 0,
                            lower_bound: 0,
                            hasRealData: false,
                            number_of_samples: 0,
                        }
                    })
                }
            },
        ],

        // Calculate error summary for banner display
        errorSummary: [
            (s) => [s.timeseries],
            (
                timeseries: ExperimentMetricTimeseries | null
            ): {
                hasErrors: boolean
                errorCount: number
                totalDays: number
                message: string
            } | null => {
                if (!timeseries?.errors || Object.keys(timeseries.errors).length === 0) {
                    return null
                }

                const errorCount = Object.keys(timeseries.errors).length
                const timeseriesDays = timeseries.timeseries ? Object.keys(timeseries.timeseries).length : 0
                const totalDays = errorCount + timeseriesDays

                const message =
                    errorCount === 1
                        ? `1 day failed to calculate`
                        : `${errorCount} of ${totalDays} days failed to calculate`

                return {
                    hasErrors: true,
                    errorCount,
                    totalDays,
                    message,
                }
            },
        ],

        // Generate Chart.js-ready datasets
        chartData: [
            (s) => [s.processedVariantData],
            (
                processedVariantData: (variantKey: string) => ProcessedTimeseriesDataPoint[]
            ): ((variantKey: string) => ProcessedChartData | null) => {
                return (variantKey: string) => {
                    const processedData = processedVariantData(variantKey)
                    if (processedData.length === 0) {
                        return null
                    }

                    const labels = processedData.map((d: ProcessedTimeseriesDataPoint) => d.date)
                    const realDataMask = processedData.map((d: ProcessedTimeseriesDataPoint) => d.hasRealData)
                    const interpolatedDataMask = processedData.map((d: ProcessedTimeseriesDataPoint) => !d.hasRealData)

                    // Values for real data (null where interpolated)
                    const realValues = processedData.map((d: ProcessedTimeseriesDataPoint, i: number) =>
                        realDataMask[i] ? (d.value ?? 0) : null
                    )
                    const realUpperBounds = processedData.map((d: ProcessedTimeseriesDataPoint, i: number) =>
                        realDataMask[i] ? (d.upper_bound ?? 0) : null
                    )
                    const realLowerBounds = processedData.map((d: ProcessedTimeseriesDataPoint, i: number) =>
                        realDataMask[i] ? (d.lower_bound ?? 0) : null
                    )

                    // For connecting segments, include boundary points
                    const connectedInterpValues = processedData.map((d: ProcessedTimeseriesDataPoint, i: number) => {
                        if (interpolatedDataMask[i]) {
                            return d.value ?? 0
                        }
                        if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                            return d.value ?? 0
                        }
                        return null
                    })
                    const connectedInterpUpperBounds = processedData.map(
                        (d: ProcessedTimeseriesDataPoint, i: number) => {
                            if (interpolatedDataMask[i]) {
                                return d.upper_bound ?? 0
                            }
                            if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                                return d.upper_bound ?? 0
                            }
                            return null
                        }
                    )
                    const connectedInterpLowerBounds = processedData.map(
                        (d: ProcessedTimeseriesDataPoint, i: number) => {
                            if (interpolatedDataMask[i]) {
                                return d.lower_bound ?? 0
                            }
                            if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                                return d.lower_bound ?? 0
                            }
                            return null
                        }
                    )

                    const datasets: ChartDataset[] = [
                        // Real upper bounds (solid)
                        {
                            label: 'Upper bound',
                            data: realUpperBounds,
                            borderColor: 'rgba(200, 200, 200, 1)',
                            borderWidth: 2,
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                        // Real lower bounds (solid, fill area)
                        {
                            label: 'Lower bound',
                            data: realLowerBounds,
                            borderColor: 'rgba(200, 200, 200, 1)',
                            borderWidth: 2,
                            fill: '-1',
                            backgroundColor: 'rgba(200, 200, 200, 0.2)',
                            tension: 0,
                            pointRadius: 0,
                        },
                        // Real variant data (solid)
                        {
                            label: variantKey,
                            data: realValues,
                            borderColor: 'rgba(0, 100, 255, 1)',
                            borderWidth: 2,
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                        // Interpolated upper bounds (dotted)
                        {
                            label: 'Interpolated Upper Bound',
                            data: connectedInterpUpperBounds,
                            borderColor: 'rgba(200, 200, 200, 0.7)',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                        // Interpolated lower bounds (dotted, fill area)
                        {
                            label: 'Interpolated Lower Bound',
                            data: connectedInterpLowerBounds,
                            borderColor: 'rgba(200, 200, 200, 0.7)',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            fill: '-1',
                            backgroundColor: 'rgba(200, 200, 200, 0.1)',
                            tension: 0,
                            pointRadius: 0,
                        },
                        // Interpolated variant data (dotted)
                        {
                            label: `${variantKey} (interpolated)`,
                            data: connectedInterpValues,
                            borderColor: 'rgba(0, 100, 255, 0.7)',
                            borderDash: [5, 5],
                            borderWidth: 2,
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                    ]

                    return {
                        labels,
                        datasets,
                        processedData,
                    }
                }
            },
        ],
    }),
])
