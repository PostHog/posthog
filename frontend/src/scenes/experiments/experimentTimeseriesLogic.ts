import { actions, afterMount, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ChartDataset as ChartJsDataset } from 'lib/Chart'
import api from 'lib/api'

import {
    ExperimentMetric,
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
    significant?: boolean
}

export interface ChartDataset extends Partial<ChartJsDataset<'line'>> {
    label: string
    data: (number | null)[]
    borderColor: string
    borderWidth: number
    borderDash?: number[]
    fill: boolean | string
    tension: number
    pointRadius: number
}

export interface ProcessedChartData {
    labels: string[]
    datasets: ChartDataset[]
    processedData: ProcessedTimeseriesDataPoint[]
}

export interface ExperimentTimeseriesLogicProps {
    experimentId: number | string
    metric?: ExperimentMetric
}

export const experimentTimeseriesLogic = kea<experimentTimeseriesLogicType>([
    props({} as ExperimentTimeseriesLogicProps),
    key((props) => props.experimentId),
    path((key) => ['scenes', 'experiments', 'experimentTimeseriesLogic', key]),

    actions(() => ({
        clearTimeseries: true,
    })),

    loaders(({ props }) => ({
        timeseries: [
            null as ExperimentMetricTimeseries | null,
            {
                loadTimeseries: async ({ metric }: { metric: ExperimentMetric }) => {
                    if (!metric.uuid) {
                        throw new Error('Metric UUID is required')
                    }
                    if (!metric.fingerprint) {
                        throw new Error('Metric fingerprint is required')
                    }

                    const response = await api.get(
                        `api/projects/@current/experiments/${props.experimentId}/timeseries_results/?metric_uuid=${metric.uuid}&fingerprint=${metric.fingerprint}`
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
                    // Show completed and partial timeseries
                    if (!timeseries?.timeseries || !['completed', 'partial'].includes(timeseries.status)) {
                        return []
                    }

                    const allTimeseriesEntries = Object.entries(timeseries.timeseries).map(([date, data]) => ({
                        date,
                        data: data as ExperimentQueryResponse,
                    }))

                    const sortedTimeseriesData = allTimeseriesEntries.sort((a, b) => a.date.localeCompare(b.date))

                    // Extract data for the specific variant with carry-forward for missing data
                    let lastKnownData: ProcessedTimeseriesDataPoint | null = null

                    return sortedTimeseriesData.map((entry) => {
                        const d = entry.data

                        // Check if this entry has actual data (not null)
                        if (d && d.variant_results && d.baseline) {
                            const variant = d.variant_results.find(
                                (v: ExperimentVariantResultFrequentist | ExperimentVariantResultBayesian) =>
                                    v.key === variantKey
                            )
                            const baseline = d.baseline

                            if (variant && baseline) {
                                const interval = getVariantInterval(variant)
                                const [lower, upper] = interval || [0, 0]
                                const delta = (lower + upper) / 2

                                const dataPoint = {
                                    date: entry.date,
                                    value: delta,
                                    upper_bound: upper,
                                    lower_bound: lower,
                                    hasRealData: true,
                                    number_of_samples: variant.number_of_samples || 0,
                                    significant: variant.significant ?? false,
                                }

                                lastKnownData = dataPoint
                                return dataPoint
                            }
                        }

                        // No data for this day - carry forward last known value if available
                        if (lastKnownData) {
                            return {
                                ...lastKnownData,
                                date: entry.date,
                                hasRealData: false, // Mark as interpolated
                            }
                        }

                        // No previous data to carry forward
                        return {
                            date: entry.date,
                            value: 0,
                            upper_bound: 0,
                            lower_bound: 0,
                            hasRealData: false,
                            number_of_samples: 0,
                            significant: false,
                        }
                    })
                }
            },
        ],

        // Progress message - only shown when we have partial data
        progressMessage: [
            (s) => [s.timeseries],
            (timeseries: ExperimentMetricTimeseries | null): string | null => {
                if (!timeseries || timeseries.status !== 'partial') {
                    return null
                }

                const timeseriesData = timeseries.timeseries || {}
                const computedDays = Object.values(timeseriesData).filter(Boolean).length
                const totalDays = Object.keys(timeseriesData).length

                return totalDays > 0 ? `Computed ${computedDays} of ${totalDays} days` : null
            },
        ],
        hasTimeseriesData: [
            (s) => [s.timeseries],
            (timeseries: ExperimentMetricTimeseries | null): boolean => {
                return !!(
                    timeseries &&
                    (timeseries.status === 'completed' || timeseries.status === 'partial') &&
                    timeseries.timeseries &&
                    Object.values(timeseries.timeseries).some((data) => data !== null)
                )
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

                    // Find the first day with a meaningful interval value (not zero)
                    const firstMeaningfulIndex = processedData.findIndex(
                        (d) =>
                            d.hasRealData &&
                            d.value !== null &&
                            d.value !== 0 &&
                            d.upper_bound !== null &&
                            d.lower_bound !== null &&
                            d.upper_bound !== 0 &&
                            d.lower_bound !== 0
                    )

                    // If meaningful data starts after day 1, trim to start from that day
                    const trimmedData =
                        firstMeaningfulIndex > 0 ? processedData.slice(firstMeaningfulIndex) : processedData

                    const labels = trimmedData.map((d: ProcessedTimeseriesDataPoint) => d.date)
                    const values = trimmedData.map((d: ProcessedTimeseriesDataPoint) => d.value)
                    const upperBounds = trimmedData.map((d: ProcessedTimeseriesDataPoint) => d.upper_bound)
                    const lowerBounds = trimmedData.map((d: ProcessedTimeseriesDataPoint) => d.lower_bound)

                    // Create a simple approach: just two datasets with segmented colors
                    const datasets: ChartDataset[] = []

                    // Upper bounds dataset
                    datasets.push({
                        label: '',
                        data: upperBounds,
                        borderColor: 'rgba(200, 200, 200, 0.8)',
                        borderWidth: 1,
                        fill: false,
                        tension: 0,
                        pointRadius: 0,
                    })

                    // Lower bounds dataset with significance-based fill
                    datasets.push({
                        label: '',
                        data: lowerBounds,
                        borderColor: 'rgba(200, 200, 200, 0.8)',
                        borderWidth: 1,
                        fill: '-1',
                        backgroundColor: (context: any) => {
                            if (context.parsed) {
                                const index = context.dataIndex
                                return trimmedData[index]?.significant
                                    ? 'rgba(34, 197, 94, 0.15)'
                                    : 'rgba(200, 200, 200, 0.15)'
                            }
                            return 'rgba(200, 200, 200, 0.15)'
                        },
                        segment: {
                            backgroundColor: (ctx: any) => {
                                const index = ctx.p0DataIndex
                                return trimmedData[index]?.significant
                                    ? 'rgba(34, 197, 94, 0.15)'
                                    : 'rgba(200, 200, 200, 0.15)'
                            },
                        },
                        tension: 0,
                        pointRadius: 0,
                    })

                    // Main variant data (always on top) with segment styling for interpolated data
                    datasets.push({
                        label: variantKey,
                        data: values,
                        borderColor: 'rgba(0, 100, 255, 1)',
                        borderWidth: 2,
                        fill: false,
                        tension: 0,
                        pointRadius: 3,
                    })

                    return {
                        labels,
                        datasets,
                        processedData: trimmedData,
                    }
                }
            },
        ],
    }),

    afterMount(({ props, actions }) => {
        if (props.metric && props.metric.uuid && props.metric.fingerprint) {
            actions.loadTimeseries({ metric: props.metric })
        }
    }),
])
