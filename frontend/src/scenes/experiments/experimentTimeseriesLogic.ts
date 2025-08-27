import { actions, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ExperimentTimeseriesDataPoint } from '~/queries/schema/schema-general'

import { getVariantInterval } from './MetricsView/new/shared/utils'
import type { experimentTimeseriesLogicType } from './experimentTimeseriesLogicType'

export interface ExperimentTimeseriesResult {
    experiment_id: number
    metric_uuid: string
    status: 'pending' | 'completed' | 'failed'
    timeseries: ExperimentTimeseriesDataPoint[] | null
    computed_at: string | null
    error_message: string | null
    created_at: string
    updated_at: string
}

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

    actions({
        loadTimeseries: (metricUuid: string) => ({ metricUuid }),
        clearTimeseries: true,
    }),

    loaders(({ props }) => ({
        timeseries: [
            null as ExperimentTimeseriesResult | null,
            {
                loadTimeseries: async ({ metricUuid }) => {
                    const response = await api.get(
                        `api/projects/@current/experiments/${props.experimentId}/timeseries_results/?metric_uuid=${metricUuid}`
                    )
                    return response
                },
                clearTimeseries: () => null,
            },
        ],
    })),

    reducers({
        currentMetricUuid: [
            null as string | null,
            {
                loadTimeseries: (_, { metricUuid }) => metricUuid,
                clearTimeseries: () => null,
            },
        ],
    }),

    selectors({
        // Extract and process timeseries data for a specific variant
        processedVariantData: [
            (s) => [s.timeseries],
            (timeseries): ((variantKey: string, endDate?: string) => ProcessedTimeseriesDataPoint[]) => {
                return (variantKey: string, endDate?: string) => {
                    if (!timeseries?.timeseries || timeseries.status !== 'completed') {
                        return []
                    }

                    let timeseriesData = timeseries.timeseries
                    if (typeof timeseriesData === 'object' && !Array.isArray(timeseriesData)) {
                        timeseriesData = (timeseriesData as any)[variantKey] || []
                    }
                    if (!Array.isArray(timeseriesData)) {
                        return []
                    }

                    // Apply optional date filter
                    const filteredData = endDate ? timeseriesData.filter((d) => d.date <= endDate) : timeseriesData

                    // Extract data for the specific variant
                    const rawProcessedData = filteredData.map((d) => {
                        // If it's already simple format (legacy), use as-is
                        if ('value' in d && d.value !== undefined) {
                            return {
                                date: d.date,
                                value: d.value,
                                upper_bound: d.upper_bound,
                                lower_bound: d.lower_bound,
                                hasRealData: true,
                            }
                        }

                        // Extract from complex experiment result structure
                        if ('variant_results' in d && 'baseline' in d && d.variant_results && d.baseline) {
                            const variant = d.variant_results.find((v) => v.key === variantKey)
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
                    })

                    // Forward-fill missing data with last known values
                    return rawProcessedData.map((d, index) => {
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

        // Generate Chart.js-ready datasets
        chartData: [
            (s) => [s.processedVariantData],
            (processedVariantData): ((variantKey: string, endDate?: string) => ProcessedChartData | null) => {
                return (variantKey: string, endDate?: string) => {
                    const processedData = processedVariantData(variantKey, endDate)
                    if (processedData.length === 0) {
                        return null
                    }

                    const labels = processedData.map((d) => d.date)
                    const realDataMask = processedData.map((d) => d.hasRealData)
                    const interpolatedDataMask = processedData.map((d) => !d.hasRealData)

                    // Values for real data (null where interpolated)
                    const realValues = processedData.map((d, i) => (realDataMask[i] ? (d.value ?? 0) : null))
                    const realUpperBounds = processedData.map((d, i) => (realDataMask[i] ? (d.upper_bound ?? 0) : null))
                    const realLowerBounds = processedData.map((d, i) => (realDataMask[i] ? (d.lower_bound ?? 0) : null))

                    // For connecting segments, include boundary points
                    const connectedInterpValues = processedData.map((d, i) => {
                        if (interpolatedDataMask[i]) {
                            return d.value ?? 0
                        }
                        if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                            return d.value ?? 0
                        }
                        return null
                    })
                    const connectedInterpUpperBounds = processedData.map((d, i) => {
                        if (interpolatedDataMask[i]) {
                            return d.upper_bound ?? 0
                        }
                        if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                            return d.upper_bound ?? 0
                        }
                        return null
                    })
                    const connectedInterpLowerBounds = processedData.map((d, i) => {
                        if (interpolatedDataMask[i]) {
                            return d.lower_bound ?? 0
                        }
                        if (i < processedData.length - 1 && interpolatedDataMask[i + 1]) {
                            return d.lower_bound ?? 0
                        }
                        return null
                    })

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
