import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ChartDataset as ChartJsDataset } from 'lib/Chart'
import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { hexToRGBA } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import {
    ExperimentMetric,
    ExperimentMetricTimeseries,
    ExperimentQueryResponse,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import { Experiment, ExperimentIdType } from '~/types'

import { COLORS } from './MetricsView/shared/colors'
import { getVariantInterval } from './MetricsView/shared/utils'
import { experimentLogic } from './experimentLogic'
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
    connect(() => ({
        values: [experimentLogic, ['experiment']],
        actions: [eventUsageLogic, ['reportExperimentTimeseriesRecalculated']],
    })),

    actions(() => ({
        clearTimeseries: true,
        recalculateTimeseries: ({ metric }: { metric: ExperimentMetric }) => ({ metric }),
    })),

    loaders(({ actions, props }) => ({
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
                recalculateTimeseries: async ({ metric }: { metric: ExperimentMetric }) => {
                    if (!metric.fingerprint) {
                        throw new Error('Metric fingerprint is required')
                    }

                    try {
                        const response = await api.createResponse(
                            `api/projects/@current/experiments/${props.experimentId}/recalculate_timeseries/`,
                            {
                                metric: metric,
                                fingerprint: metric.fingerprint,
                            }
                        )

                        if (response.ok) {
                            if (response.status === 201) {
                                lemonToast.success('Recalculation started successfully')
                                actions.reportExperimentTimeseriesRecalculated(
                                    props.experimentId as ExperimentIdType,
                                    metric
                                )
                            } else if (response.status === 200) {
                                lemonToast.info('Recalculation already in progress')
                            }
                        }
                    } catch (error) {
                        lemonToast.error('Failed to start recalculation')
                        throw error
                    }

                    return null
                },
            },
        ],
    })),

    selectors({
        isRecalculating: [
            (s) => [s.timeseries],
            (timeseries: ExperimentMetricTimeseries | null): boolean => {
                return (
                    timeseries?.recalculation_status === 'pending' || timeseries?.recalculation_status === 'in_progress'
                )
            },
        ],
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
            (s) => [s.processedVariantData, s.experiment],
            (
                processedVariantData: (variantKey: string) => ProcessedTimeseriesDataPoint[],
                experiment: Experiment
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

                    // Get variant index from the experiment's stable feature_flag_variants order
                    let variantIndex = 0
                    if (experiment?.parameters?.feature_flag_variants) {
                        const idx = experiment.parameters.feature_flag_variants.findIndex(
                            (v: any) => v.key === variantKey
                        )
                        if (idx !== -1) {
                            variantIndex = idx
                        }
                    }

                    const variantColor = getSeriesColor(variantIndex)

                    // Create a simple approach: just two datasets with segmented colors
                    const datasets: ChartDataset[] = []

                    // Upper bounds dataset
                    datasets.push({
                        label: 'Upper bound',
                        data: upperBounds,
                        borderColor: COLORS.BAR_DEFAULT,
                        borderWidth: 1,
                        fill: false,
                        tension: 0,
                        pointRadius: 0,
                    })

                    // Lower bounds dataset with significance-based fill
                    datasets.push({
                        label: 'Lower bound',
                        data: lowerBounds,
                        borderColor: COLORS.BAR_DEFAULT,
                        borderWidth: 1,
                        fill: '-1',
                        backgroundColor: (context: any) => {
                            if (context.parsed) {
                                const index = context.dataIndex
                                const dataPoint = trimmedData[index]
                                if (dataPoint?.significant) {
                                    // Check if delta is positive or negative
                                    const isPositive = dataPoint.value !== null && dataPoint.value > 0
                                    return isPositive
                                        ? hexToRGBA(COLORS.BAR_POSITIVE, 0.15)
                                        : hexToRGBA(COLORS.BAR_NEGATIVE, 0.15)
                                }
                                return hexToRGBA(COLORS.BAR_DEFAULT, 0.1)
                            }
                            return hexToRGBA(COLORS.BAR_DEFAULT, 0.1)
                        },
                        segment: {
                            backgroundColor: (ctx: any) => {
                                const index = ctx.p0DataIndex
                                const dataPoint = trimmedData[index]
                                if (dataPoint?.significant) {
                                    // Check if delta is positive or negative
                                    const isPositive = dataPoint.value !== null && dataPoint.value > 0
                                    return isPositive
                                        ? hexToRGBA(COLORS.BAR_POSITIVE, 0.15)
                                        : hexToRGBA(COLORS.BAR_NEGATIVE, 0.15)
                                }
                                return hexToRGBA(COLORS.BAR_DEFAULT, 0.1)
                            },
                        },
                        tension: 0,
                        pointRadius: 0,
                    })

                    // Main variant data (always on top) with segment styling for interpolated data
                    datasets.push({
                        label: 'Delta',
                        data: values,
                        borderColor: variantColor,
                        borderWidth: 2,
                        fill: false,
                        tension: 0,
                        pointRadius: 3,
                        pointBackgroundColor: (context: any) => {
                            if (context.parsed) {
                                const index = context.dataIndex
                                const dataPoint = trimmedData[index]
                                // Use dimmed color for interpolated data points
                                return dataPoint?.hasRealData ? variantColor : hexToRGBA(variantColor, 0.5)
                            }
                            return variantColor
                        },
                        pointBorderColor: (context: any) => {
                            if (context.parsed) {
                                const index = context.dataIndex
                                const dataPoint = trimmedData[index]
                                // Use dimmed color for interpolated data points
                                return dataPoint?.hasRealData ? variantColor : hexToRGBA(variantColor, 0.5)
                            }
                            return variantColor
                        },
                        segment: {
                            borderColor: (ctx: any) => {
                                // The segment leads FROM p0 TO p1
                                // Dim the color if the end point (p1) has no real data
                                const endIndex = ctx.p1DataIndex
                                const endDataPoint = trimmedData[endIndex]
                                return endDataPoint?.hasRealData ? variantColor : hexToRGBA(variantColor, 0.5)
                            },
                            borderDash: (ctx: any) => {
                                // Make it dashed if the end point (p1) has no real data
                                const endIndex = ctx.p1DataIndex
                                const endDataPoint = trimmedData[endIndex]
                                return endDataPoint?.hasRealData ? [] : [5, 5]
                            },
                        },
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

    listeners(({ actions }) => ({
        recalculateTimeseriesSuccess: ({ payload }) => {
            const metric = payload?.metric
            if (metric) {
                actions.loadTimeseries({ metric })
            }
        },
    })),

    afterMount(({ props, actions }) => {
        if (props.metric && props.metric.uuid && props.metric.fingerprint) {
            actions.loadTimeseries({ metric: props.metric })
        }
    }),
])
