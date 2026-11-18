import { useEffect, useRef, useState } from 'react'

import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { performQuery } from '~/queries/query'
import {
    ExperimentExposureCriteria,
    ExperimentFunnelMetricStep,
    ExperimentMetric,
    ExperimentMetricSource,
    ExperimentMetricType,
    ExperimentRetentionStart,
    NodeKind,
    isExperimentExposureNode,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentQuantileMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType, FunnelConversionWindowTimeUnit } from '~/types'

import {
    EMPTY_WAREHOUSE_NATIVE_BINDING,
    getWarehouseNativeBinding,
    getWarehouseNativeExposure,
    metricUsesWarehouseNativeSource,
    toWarehouseNativeMetric,
} from 'products/experiments/frontend/warehouseNative/warehouseNativeSources'

import { isThresholdAvailableForMath } from './ExperimentMetricThreshold'
import { EXPOSURE_DEFAULT_EVENT, getActivationConfig, isDefaultExposureConfig } from './exposureContract'
import { seriesToMetricConfig, toQuantileSource } from './metricQueryUtils'
import {
    getAllowedMathTypes,
    getDefaultExperimentMetric,
    getEventCountQuery,
    getExposureConfigDisplayName,
    getMathAvailability,
} from './utils'

export function getExposureCriteriaLabel(
    exposureCriteria: ExperimentExposureCriteria | undefined,
    defaultEvent: string = EXPOSURE_DEFAULT_EVENT
): string {
    const exposureConfig = exposureCriteria?.exposure_config
    if (!exposureConfig || isDefaultExposureConfig(exposureConfig)) {
        return defaultEvent
    }

    return getExposureConfigDisplayName(exposureConfig)
}

const loadEventCount = async (
    metric: ExperimentMetric,
    filterTestAccounts: boolean,
    setEventCount: (count: number | null) => void,
    setIsLoading: (loading: boolean) => void
): Promise<void> => {
    setIsLoading(true)
    try {
        const query = getEventCountQuery(metric, filterTestAccounts)

        if (!query) {
            setEventCount(0)
            return
        }

        const response = await performQuery(query)

        let count = 0
        if (response.results.length > 0) {
            const firstResult = response.results[0]
            if (firstResult && typeof firstResult.aggregated_value === 'number') {
                count = firstResult.aggregated_value
            }
        }

        setEventCount(count)
    } catch (error) {
        lemonToast.error(JSON.stringify(error))
        setEventCount(0)
    } finally {
        setIsLoading(false)
    }
}

export const dataWarehousePopoverFields: DataWarehousePopoverField[] = [
    {
        key: 'timestamp_field',
        label: 'Timestamp Field',
        description: 'The column in your data warehouse table that contains the timestamp of each row',
    },
    {
        key: 'data_warehouse_join_key',
        label: 'Data Warehouse Join Key',
        description:
            'The column in your data warehouse table that identifies which user each row belongs to (e.g. user_id, email)',
        allowHogQL: true,
    },
    {
        key: 'events_join_key',
        label: 'Events Join Key',
        description: 'The field on PostHog events to match against the data warehouse join key (usually distinct_id)',
        allowHogQL: true,
        hogQLOnly: true,
        tableName: 'events',
    },
]

/** The sources every metric type accepts: those the series picker can produce. */
const isPickerSource = (source: ExperimentMetricSource | undefined): source is ExperimentFunnelMetricStep =>
    !!source &&
    (source.kind === NodeKind.EventsNode ||
        source.kind === NodeKind.ActionsNode ||
        source.kind === NodeKind.ExperimentDataWarehouseNode)

const getMetricSources = (metric: ExperimentMetric): ExperimentMetricSource[] => {
    if (isExperimentMeanMetric(metric) || isExperimentQuantileMetric(metric)) {
        return [metric.source]
    }
    if (isExperimentFunnelMetric(metric)) {
        return metric.series
    }
    if (isExperimentRatioMetric(metric)) {
        return metric.denominator ? [metric.numerator, metric.denominator] : [metric.numerator]
    }
    if (isExperimentRetentionMetric(metric)) {
        // An exposure-anchored start has no literal event to carry over
        const startSources = isExperimentExposureNode(metric.start_event) ? [] : [metric.start_event]
        return metric.completion_event ? [...startSources, metric.completion_event] : startSources
    }
    return []
}

export const POSTHOG_SOURCE_BLOCKED =
    "This experiment's exposure is a warehouse-native query, so its metrics must be warehouse-native too."
export const WAREHOUSE_SOURCE_BLOCKED = "Set this experiment's exposure to a warehouse-native query first."
export const DATA_SOURCE_HELP =
    'A warehouse-native metric runs a SQL query in your own warehouse through a direct connection. Only the aggregated results leave the warehouse.'
export const EXPOSURE_HELP =
    'Metrics are only counted for users who have been exposed to the experiment. This ensures fair comparison between control and test groups.'
export const EXPOSURE_DOCS_URL = 'https://posthog.com/docs/experiments/exposures'
export function exposureSharingHelp(hasExposureCriteria: boolean): string {
    return hasExposureCriteria
        ? 'The exposure event is shared across all metrics in this experiment.'
        : 'The exposure event will be configured at the experiment level and shared across all metrics.'
}
export const HOGQL_HELP =
    'SQL expressions allow you to write custom computations and aggregations. The expression should return a numeric value and will be evaluated for each user in the experiment.'
export const HOGQL_DOCS_URL = 'https://posthog.com/docs/hogql/expressions'
export const RETENTION_START_HELP =
    'The event that triggers retention tracking. Retention is measured from when users perform this event.'
export function retentionExposureStartHelp(isSharedMetric: boolean): string {
    return isSharedMetric
        ? "Retention starts from each user's first exposure. Each experiment using this metric anchors on its own exposure event."
        : "Retention starts from each user's first exposure to the experiment."
}
export const RETENTION_COMPLETION_HELP =
    "The event that indicates a user was 'retained'. We check if users who performed the start event also perform this event within the retention window."
export const RETENTION_WINDOW_HELP =
    'The time period after the start event during which we check for the completion event.'
export const RETENTION_WINDOW_EXAMPLE =
    '"From 7 to 14 days" captures completions from day 7 through day 14 (inclusive).'
export const START_HANDLING_HELP =
    'Choose how to handle users who perform the start event multiple times during the experiment.'
export const GOAL_HELP = 'For example, conversion rates should increase, while bounce rates should decrease.'
export const RECENT_ACTIVITY_HELP = 'This shows recent activity for your selected metric over the past 2 weeks.'
export const RECENT_ACTIVITY_HEALTH_HELP =
    "It's a quick health check to ensure your tracking is working properly, so that you'll receive accurate results when your experiment starts."

export interface ExperimentMetricFormProps {
    metric: ExperimentMetric
    isSharedMetric?: boolean
    handleSetMetric: (newMetric: ExperimentMetric) => void
    filterTestAccounts: boolean
    exposureCriteria?: ExperimentExposureCriteria | undefined
    openExposureCriteriaModal?: (exposureCriteria?: ExperimentExposureCriteria) => void
    /**
     * The experiment's server-resolved default exposure event. Omitted for shared metrics, which
     * aren't tied to one experiment and so have no resolvable event.
     */
    resolvedExposureEvent?: string
}

export interface MetricTypeOption {
    value: ExperimentMetricType
    label: string
    'data-attr': string
    disabledReason?: string
    description: string
}

export interface ExperimentMetricFormModel {
    showDataSource: boolean
    usesWarehouseNative: boolean
    handleDataSourceChange: (dataSource: 'posthog' | 'warehouse_native') => void
    warehouseExposure: ReturnType<typeof getWarehouseNativeExposure>
    handleMetricTypeChange: (newMetricType: ExperimentMetricType) => void
    radioOptions: MetricTypeOption[]
    activationConfig: ReturnType<typeof getActivationConfig>
    handleSetSeries: (series: SeriesNode[]) => void
    mathAvailability: ReturnType<typeof getMathAvailability>
    allowedMathTypes: ReturnType<typeof getAllowedMathTypes>
    hideDeleteBtn: (_: any, index: number) => boolean
    setRetentionStartSource: (value: 'custom' | 'exposure') => void
    isLoading: boolean
    eventCount: number | null
    getEventTypeLabel: () => string
}

export function useExperimentMetricForm({
    metric,
    handleSetMetric,
    filterTestAccounts,
    exposureCriteria,
}: ExperimentMetricFormProps): ExperimentMetricFormModel {
    const mathAvailability = getMathAvailability(metric.metric_type)
    const allowedMathTypes = getAllowedMathTypes(metric.metric_type)
    const warehouseNativeEnabled = useFeatureFlag('BIGQUERY_DIRECT_QUERY')
    const warehouseExposure = getWarehouseNativeExposure(exposureCriteria)
    const usesWarehouseNative = metricUsesWarehouseNativeSource(metric)
    // Keep an existing warehouse-native metric editable even if the team is no longer flagged in
    const showDataSource = warehouseNativeEnabled || usesWarehouseNative || !!warehouseExposure
    const quantileMetricsEnabled = useFeatureFlag('EXPERIMENTS_QUANTILE_METRICS')
    // A percentile metric that exists already must keep its type in the picker when the team is not flagged in
    const showQuantileOption = quantileMetricsEnabled || isExperimentQuantileMetric(metric)
    const [eventCount, setEventCount] = useState<number | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    // holds the custom start configuration while the exposure sentinel is selected, so switching back restores it
    const previousRetentionStart = useRef<{
        start_event: ExperimentRetentionStart
        start_handling: 'first_seen' | 'last_seen'
        conversion_window?: number
        conversion_window_unit?: FunnelConversionWindowTimeUnit
    } | null>(null)

    const getEventTypeLabel = (): string => {
        if (isExperimentMeanMetric(metric) || isExperimentQuantileMetric(metric)) {
            return metric.source.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (isExperimentFunnelMetric(metric)) {
            const lastStep = metric.series[metric.series.length - 1]
            return lastStep?.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (isExperimentRatioMetric(metric)) {
            return 'events'
        }
        return 'events'
    }

    const handleSetSeries = (series: SeriesNode[]): void => {
        const metricConfig = seriesToMetricConfig(metric.metric_type, series)
        if (metricConfig) {
            const updatedMetric = { ...metric, ...metricConfig }
            /**
             * Switching to a math type that doesn't support thresholds must clear any stale
             * threshold, otherwise the disabled threshold input traps the value and outlier
             * handling stays disabled with no way to recover.
             */
            if (isExperimentMeanMetric(updatedMetric) && !isThresholdAvailableForMath(updatedMetric.source.math)) {
                updatedMetric.threshold = undefined
            }
            handleSetMetric(updatedMetric)
        }
    }

    const handleMetricTypeChange = (newMetricType: ExperimentMetricType): void => {
        const sources = getMetricSources(metric)

        const newMetric = getDefaultExperimentMetric(newMetricType)

        // Apply the existing sources to the new metric type to preserve selections
        if (sources.length > 0 && sources[0]) {
            if (newMetricType === ExperimentMetricType.MEAN && isExperimentMeanMetric(newMetric)) {
                newMetric.source = sources[0]
            } else if (newMetricType === ExperimentMetricType.FUNNEL && isExperimentFunnelMetric(newMetric)) {
                newMetric.series = sources.filter(isPickerSource)
            } else if (newMetricType === ExperimentMetricType.RATIO && isExperimentRatioMetric(newMetric)) {
                newMetric.numerator = sources[0]
            } else if (newMetricType === ExperimentMetricType.RETENTION && isExperimentRetentionMetric(newMetric)) {
                if (isPickerSource(sources[0])) {
                    newMetric.start_event = sources[0]
                }
                if (isPickerSource(sources[1])) {
                    newMetric.completion_event = sources[1]
                }
            } else if (newMetricType === ExperimentMetricType.QUANTILE && isExperimentQuantileMetric(newMetric)) {
                newMetric.source = toQuantileSource(sources[0]) ?? newMetric.source
            }
        }

        const typedMetric = {
            ...newMetric,
            // Keep the current uuid and name
            uuid: metric.uuid,
            name: metric.name,
        }
        // A new metric type starts with event sources, which a warehouse-native metric cannot mix in
        handleSetMetric(
            usesWarehouseNative
                ? toWarehouseNativeMetric(typedMetric, warehouseExposure ?? getWarehouseNativeBinding(metric))
                : typedMetric
        )
    }

    const handleDataSourceChange = (dataSource: 'posthog' | 'warehouse_native'): void => {
        // The segmented button also reports a click on the selected option, which must not reset the metric
        if ((dataSource === 'warehouse_native') === usesWarehouseNative) {
            return
        }
        if (dataSource === 'warehouse_native') {
            handleSetMetric(toWarehouseNativeMetric(metric, warehouseExposure ?? EMPTY_WAREHOUSE_NATIVE_BINDING))
        } else {
            handleSetMetric({
                ...getDefaultExperimentMetric(metric.metric_type),
                uuid: metric.uuid,
                name: metric.name,
                goal: metric.goal,
            })
        }
    }

    const warehouseNativeTypeReason = usesWarehouseNative
        ? 'A warehouse-native metric can be a mean or a ratio.'
        : undefined

    const radioOptions: MetricTypeOption[] = [
        {
            value: ExperimentMetricType.FUNNEL,
            label: 'Funnel',
            'data-attr': 'experiment-metric-type-funnel',
            disabledReason: warehouseNativeTypeReason,
            description:
                'Calculates the percentage of users exposed to the experiment who completed the funnel. Useful for measuring conversion rates.',
        },
        {
            value: ExperimentMetricType.MEAN,
            label: 'Mean',
            'data-attr': 'experiment-metric-type-mean',
            description:
                'Calculates the value per user exposed to the experiment. Useful for measuring count of clicks, revenue or other numeric values.',
        },
        {
            value: ExperimentMetricType.RATIO,
            label: 'Ratio',
            'data-attr': 'experiment-metric-type-ratio',
            description:
                'Calculates the ratio between two metrics. Useful when you want to use a different denominator than users exposed to the experiment.',
        },
        {
            value: ExperimentMetricType.RETENTION,
            label: 'Retention',
            'data-attr': 'experiment-metric-type-retention',
            disabledReason: warehouseNativeTypeReason,
            description:
                'Calculates the retention rate of users exposed to the experiment. Useful for measuring the percentage of users who return to the app after a certain period of time.',
        },
        ...(showQuantileOption
            ? [
                  {
                      value: ExperimentMetricType.QUANTILE,
                      label: 'Percentile',
                      'data-attr': 'experiment-metric-type-quantile',
                      disabledReason: warehouseNativeTypeReason,
                      description:
                          'Calculates a percentile of a numeric property across all events, such as p90 page load time. Useful for measuring latency and other durations.',
                  },
              ]
            : []),
    ]

    // dependencies for the loadEventCount useEffect call
    const singleSource = isExperimentMeanMetric(metric) || isExperimentQuantileMetric(metric) ? metric.source : null
    const funnelSeries = isExperimentFunnelMetric(metric) ? metric.series : null
    const ratioNumerator = isExperimentRatioMetric(metric) ? metric.numerator : null
    const ratioDenominator = isExperimentRatioMetric(metric) ? metric.denominator : null
    const retentionStartEvent = isExperimentRetentionMetric(metric) ? metric.start_event : null
    const retentionCompletionEvent = isExperimentRetentionMetric(metric) ? metric.completion_event : null

    useEffect(() => {
        loadEventCount(metric, filterTestAccounts, setEventCount, setIsLoading)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        metric.metric_type,
        singleSource,
        funnelSeries,
        ratioNumerator,
        ratioDenominator,
        retentionStartEvent,
        retentionCompletionEvent,
        filterTestAccounts,
    ])

    const hideDeleteBtn = (_: any, index: number): boolean => index === 0

    const activationConfig = getActivationConfig(exposureCriteria)

    const setRetentionStartSource = (value: 'custom' | 'exposure'): void => {
        if (!isExperimentRetentionMetric(metric)) {
            return
        }
        if (value === 'exposure') {
            if (!isExperimentExposureNode(metric.start_event)) {
                previousRetentionStart.current = {
                    start_event: metric.start_event,
                    start_handling: metric.start_handling,
                    conversion_window: metric.conversion_window,
                    conversion_window_unit: metric.conversion_window_unit,
                }
            }
            // the backend rejects a conversion window or 'last_seen' start handling on an exposure start
            handleSetMetric({
                ...metric,
                start_event: { kind: NodeKind.ExperimentExposureNode },
                start_handling: 'first_seen',
                conversion_window: undefined,
                conversion_window_unit: undefined,
            })
        } else {
            const previous = previousRetentionStart.current
            handleSetMetric({
                ...metric,
                start_event: previous?.start_event ?? {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: ExperimentMetricMathType.TotalCount,
                },
                start_handling: previous?.start_handling ?? 'first_seen',
                conversion_window: previous?.conversion_window,
                conversion_window_unit: previous?.conversion_window_unit,
            })
        }
    }

    return {
        showDataSource,
        usesWarehouseNative,
        handleDataSourceChange,
        warehouseExposure,
        handleMetricTypeChange,
        radioOptions,
        activationConfig,
        handleSetSeries,
        mathAvailability,
        allowedMathTypes,
        hideDeleteBtn,
        setRetentionStartSource,
        isLoading,
        eventCount,
        getEventTypeLabel,
    }
}
