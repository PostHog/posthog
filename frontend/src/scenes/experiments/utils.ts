import { match } from 'ts-pattern'

import { getSeriesColor } from 'lib/colors'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout, MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { captureAccessControlEvent } from 'lib/utils/accessControlUtils'
import { uuid } from 'lib/utils/dom'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import {
    AnyDataWarehouseNode,
    AnyEntityNode,
    CachedNewExperimentQueryResponse,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentExposureConfig,
    ExperimentFunnelMetricStep,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricSource,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    GroupNode,
    NodeKind,
    ProductKey,
    TrendsQuery,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isNodeWithSource, isTrendsQuery, isValidQueryForExperiment } from '~/queries/utils'
import {
    ChartDisplayType,
    Experiment,
    ExperimentIdType,
    ExperimentMetricGoal,
    ExperimentMetricMathType,
    FeatureFlagBasicType,
    FeatureFlagType,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    MultivariateFlagVariant,
    PropertyFilterType,
    PropertyOperator,
    type QueryBasedInsightModel,
    UniversalFiltersGroupValue,
} from '~/types'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'products/experiments/frontend/constants'
import type {
    ExperimentFeatureFlagFiltersApi,
    ExperimentFeatureFlagInputApi,
} from 'products/experiments/frontend/generated/api.schemas'

import {
    EXPOSURE_DEFAULT_EVENT,
    EXPOSURE_FEATURE_FLAG_PROPERTY,
    EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY,
    featureFlagVariantProperty,
    resolvedExposureEvent,
} from './exposureContract'
import { SharedMetric } from './SharedMetrics/sharedMetricLogic'

const MULTIPLE_VARIANT_WARNING_THRESHOLD = 0.5 // on the 0-100 scale (0.5 = 0.5%)

export function filterLowMultipleVariant<T extends { variant: string; percentage: number }>(variants: T[]): T[] {
    return variants.filter(
        (v) => v.variant !== EXPERIMENT_VARIANT_MULTIPLE || v.percentage > MULTIPLE_VARIANT_WARNING_THRESHOLD
    )
}

/**
 * Resolves the effective multi-variant handling, applying the backend default when unset.
 * See posthog/hogql_queries/experiments/exposure_query_logic.py (default = `EXCLUDE`).
 */
export function resolveMultipleVariantHandling(
    handling: 'exclude' | 'first_seen' | undefined
): 'exclude' | 'first_seen' {
    return handling ?? 'exclude'
}

export function isEventExposureConfig(config: ExperimentExposureConfig): config is ExperimentEventExposureConfig {
    return config.kind === NodeKind.ExperimentEventExposureConfig || 'event' in config
}

export function getExposureConfigDisplayName(config: ExperimentExposureConfig): string {
    return isEventExposureConfig(config) ? config.event || 'Unknown Event' : config.name || `Action ${config.id}`
}

export function getVariantColor(variantKey: string, featureFlagVariants: MultivariateFlagVariant[]): string {
    const variantIndex = featureFlagVariants.findIndex((v) => v.key === variantKey)
    return variantIndex !== -1 ? getSeriesColor(variantIndex) : 'var(--muted)'
}

/**
 * A save on the variants tab that access control refused. Access-denied responses are kept out of
 * exception capture, so without this the blocked share of these saves has no signal at all.
 * `blockedAt` says whether the form refused the save, or the server did after the form let it
 * through.
 */
export function captureVariantsSaveBlocked(
    experimentId: ExperimentIdType | undefined,
    surface: 'distribution' | 'release_conditions',
    blockedAt: 'form' | 'request'
): void {
    captureAccessControlEvent('experiment variants save blocked', {
        experiment_id: experimentId,
        surface,
        blocked_at: blockedAt,
    })
}

/**
 * Variants for an experiment. Saved experiments resolve from the linked feature flag (the source
 * of truth); an unsaved draft has no flag yet, so it resolves from the draft flag config instead.
 */
export function getExperimentVariants(experiment: Partial<Experiment> | null | undefined): MultivariateFlagVariant[] {
    return (
        experiment?.feature_flag?.filters?.multivariate?.variants ??
        experiment?.feature_flag_config?.filters?.multivariate?.variants ??
        []
    )
}

/**
 * Variants for a standalone feature flag (no experiment in hand). Reads the flag's saved config only.
 */
export function getFlagVariants(
    flag: FeatureFlagBasicType | FeatureFlagType | null | undefined
): MultivariateFlagVariant[] {
    return flag?.filters?.multivariate?.variants ?? []
}

/**
 * The effective baseline variant, mirroring the backend rule (get_baseline_variant_key):
 * the configured stats_config.baseline_variant_key, else 'control' when the flag has one,
 * else the flag's first variant. A control-less draft can lack the configured key until
 * launch pins it, so callers must not assume 'control' exists.
 */
export function getBaselineVariantKey(experiment: Partial<Experiment> | null | undefined): string {
    const configured = experiment?.stats_config?.baseline_variant_key
    if (configured) {
        return configured
    }
    const variants = getExperimentVariants(experiment)
    if (variants.length === 0 || variants.some((variant) => variant.key === 'control')) {
        return 'control'
    }
    return variants[0].key
}

export function formatUnitByQuantity(value: number, unit: string): string {
    return value === 1 ? unit : unit + 's'
}

export function ensureIsPercent(value: string | number | undefined): number {
    const parsedNum = typeof value === 'string' ? parseInt(value, 10) : (value ?? 0)
    const num = isNaN(parsedNum) ? 0 : parsedNum
    return Math.min(100, Math.max(0, num))
}

export function percentageDistribution(variantCount: number): number[] {
    const basePercentage = Math.floor(100 / variantCount)
    const percentages = Array.from<number>({ length: variantCount }).fill(basePercentage)
    let remaining = 100 - basePercentage * variantCount
    for (let i = 0; remaining > 0; i++, remaining--) {
        // try to equally distribute `remaining` across variants
        percentages[i] += 1
    }
    return percentages
}

export function isEvenlyDistributed(variants: MultivariateFlagVariant[]): boolean {
    const evenPercentages = percentageDistribution(variants.length)
    return variants.every((variant, index) => variant.rollout_percentage === evenPercentages[index])
}

function seriesToFilterLegacy(
    series: AnyEntityNode<AnyDataWarehouseNode> | GroupNode,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue | null {
    if (series.kind === NodeKind.EventsNode) {
        return {
            id: series.event as string,
            name: series.event as string,
            type: 'events',
            properties: [
                {
                    key: featureFlagVariantProperty(featureFlagKey),
                    type: PropertyFilterType.Event,
                    value: [variantKey],
                    operator: PropertyOperator.Exact,
                },
            ],
        }
    } else if (series.kind === NodeKind.ActionsNode) {
        return {
            id: series.id,
            name: series.name,
            type: 'actions',
        }
    }
    return null
}

function seriesToFilter(series: AnyEntityNode | ExperimentMetricSource): UniversalFiltersGroupValue | null {
    if (series.kind === NodeKind.EventsNode) {
        return {
            id: series.event ?? null,
            name: series.event as string,
            type: 'events',
            properties: series.properties ?? [],
        }
    }

    if (series.kind === NodeKind.ActionsNode) {
        return {
            id: series.id,
            name: series.name,
            type: 'actions',
        }
    }

    if (series.kind === NodeKind.ExperimentDataWarehouseNode) {
        return {
            id: series.table_name,
            name: series.name,
            type: 'data_warehouse',
        }
    }

    return null
}

/**
 * Event/action filters for one metric's sources — the "session reached this metric" part of a
 * recordings query. Data-warehouse sources have no session events and are skipped, so a metric
 * whose every source is a data-warehouse node (or a retention metric, whose steps the recordings
 * surfaces don't enumerate) yields no filters.
 */
export function getMetricSessionFilters(metric: ExperimentMetric): UniversalFiltersGroupValue[] {
    const sources: (ExperimentMetricSource | ExperimentFunnelMetricStep)[] = isExperimentMeanMetric(metric)
        ? [metric.source]
        : isExperimentFunnelMetric(metric)
          ? metric.series
          : isExperimentRatioMetric(metric)
            ? [metric.numerator, metric.denominator]
            : []
    return sources
        .filter((source) => source.kind === NodeKind.EventsNode || source.kind === NodeKind.ActionsNode)
        .map((source) => seriesToFilter(source))
        .filter((filter): filter is UniversalFiltersGroupValue => filter !== null)
}

/**
 * The distinct events a metric counts. A metric's name is free text ("Rageclicks per user"), so
 * on its own it doesn't say what a session has to have fired to match.
 */
export function getMetricSourceEventNames(metric: ExperimentMetric): string[] {
    const names = getMetricSessionFilters(metric)
        // Only entity filters name an event; a nested filter group (which the type allows) doesn't.
        .flatMap((filter) => ('id' in filter ? [String(filter.name ?? filter.id ?? '')] : []))
        .filter(Boolean)
    return [...new Set(names)]
}

export const NOT_A_FUNNEL_REASON = "This filter reads a funnel's last step, so it needs a funnel metric."

export const FUNNEL_SERVER_SIDE_COMPLETION_REASON =
    "This filter reads a funnel's last step. This one is captured server-side without a session ID, so recordings can't be matched."

export const FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON =
    "This filter reads a funnel's last step. This one is measured in the data warehouse, which has no session events to match recordings on."

/**
 * Why drop-off can't be asked of this metric, or null when it can. An experiment funnel's first
 * step is always the exposure event (the analysis prepends it), so drop-off reads only the
 * funnel's last step, and that step alone has to be matchable. The whole-metric linkability
 * check can't stand in for this, since a funnel stays matchable on its other steps. Mirrors the
 * `session_buckets` endpoint, which refuses the same shapes rather than counting a completion no
 * recording can show as zero in every session.
 */
export function getFunnelDropoffReason(metric: ExperimentMetric, unlinkableEventNames: Set<string>): string | null {
    if (!isExperimentFunnelMetric(metric) || metric.series.length === 0) {
        return NOT_A_FUNNEL_REASON
    }
    const completion = metric.series[metric.series.length - 1]
    if (completion.kind === NodeKind.ExperimentDataWarehouseNode) {
        return FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON
    }
    if (completion.kind === NodeKind.EventsNode && completion.event && unlinkableEventNames.has(completion.event)) {
        return FUNNEL_SERVER_SIDE_COMPLETION_REASON
    }
    return null
}

/**
 * Whether a recordings event filter can only match zero sessions: the project has never seen the
 * event with a `$session_id` (e.g. it is captured server-side). Action and data warehouse filters
 * pass through unchecked, matching the replay playlist's own posture.
 */
export function isUnlinkableEventFilter(
    filter: UniversalFiltersGroupValue,
    unlinkableEventNames: Set<string>
): boolean {
    return (
        'type' in filter &&
        filter.type === 'events' &&
        'name' in filter &&
        typeof filter.name === 'string' &&
        unlinkableEventNames.has(filter.name)
    )
}

export const METRIC_UNLINKABLE_REASON =
    "This metric's events are captured server-side without a session ID, so recordings can't be matched."

export const RETENTION_UNLINKABLE_REASON =
    'Retention metrics measure a return visit, which happens in a later session than the one that starts it. No single recording can show both, so these metrics are left out of the filter.'

export const DATA_WAREHOUSE_UNLINKABLE_REASON =
    'This metric is measured entirely in the data warehouse, which has no session events to match recordings on.'

/**
 * Why a metric can't narrow a recordings list, or null when it can. A metric is unlinkable when
 * every one of its sources is a never-session-linked event, or when it yields no session filter at
 * all (a retention metric, or one measured only in the data warehouse). Either way its filter could
 * only match zero sessions. Pass an empty `unlinkableEventNames` while the linkability check loads,
 * which fails open, the posture every linkability consumer shares.
 */
export function getMetricUnlinkableReason(metric: ExperimentMetric, unlinkableEventNames: Set<string>): string | null {
    const filters = getMetricSessionFilters(metric)
    if (filters.length === 0) {
        return isExperimentRetentionMetric(metric) ? RETENTION_UNLINKABLE_REASON : DATA_WAREHOUSE_UNLINKABLE_REASON
    }
    return filters.every((filter) => isUnlinkableEventFilter(filter, unlinkableEventNames))
        ? METRIC_UNLINKABLE_REASON
        : null
}

/**
 * The single event an experiment's exposure is counted on, for the session-linkability check.
 * Null for an action exposure config, which can match several events, so no one name applies.
 */
export function getExposureLinkabilityEventName(experiment: Experiment): string | null {
    const exposureConfig = experiment.exposure_criteria?.exposure_config
    if (exposureConfig && !(isEventExposureConfig(exposureConfig) && exposureConfig.event === EXPOSURE_DEFAULT_EVENT)) {
        return isEventExposureConfig(exposureConfig) && exposureConfig.event ? exposureConfig.event : null
    }
    return resolvedExposureEvent(experiment)
}

/**
 * Event names whose session-linkability must be checked before building "View recordings" links:
 * the exposure event plus every plain-event metric step across primary, secondary and shared
 * metrics. Action and data warehouse steps pass through unchecked (same as the replay playlist's
 * own check), as do "all events" steps, which have no event name.
 */
export function getSessionLinkabilityEventNames(experiment: Experiment): string[] {
    const eventNames = new Set<string>()

    const exposureEventName = getExposureLinkabilityEventName(experiment)
    if (exposureEventName) {
        eventNames.add(exposureEventName)
    }

    const metrics = [
        ...(experiment.metrics || []),
        ...(experiment.metrics_secondary || []),
        ...(experiment.saved_metrics || []).map((savedMetric: { query?: ExperimentMetric }) => savedMetric?.query),
    ].filter((metric): metric is ExperimentMetric => metric?.kind === NodeKind.ExperimentMetric)

    for (const metric of metrics) {
        const sources: (ExperimentMetricSource | ExperimentFunnelMetricStep)[] = isExperimentMeanMetric(metric)
            ? [metric.source]
            : isExperimentFunnelMetric(metric)
              ? metric.series
              : isExperimentRatioMetric(metric)
                ? [metric.numerator, metric.denominator]
                : []
        for (const source of sources) {
            if (source.kind === NodeKind.EventsNode && source.event) {
                eventNames.add(source.event)
            }
        }
    }

    return Array.from(eventNames)
}

export function getViewRecordingFiltersLegacy(
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue[] {
    const filters: UniversalFiltersGroupValue[] = []
    if (metric.kind === NodeKind.ExperimentMetric) {
        if (isExperimentMeanMetric(metric)) {
            if (metric.source.kind === NodeKind.EventsNode) {
                return [
                    {
                        id: metric.source.event ?? null,
                        name: metric.source.event,
                        type: 'events',
                        properties: [
                            {
                                key: featureFlagVariantProperty(featureFlagKey),
                                type: PropertyFilterType.Event,
                                value: [variantKey],
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ]
            }
        }
        return []
    } else if (metric.kind === NodeKind.ExperimentTrendsQuery) {
        if (metric.exposure_query) {
            const exposureSeries = metric.exposure_query.series[0]
            // Experiments don't support GroupNode yet - skip if it's a group
            if (exposureSeries.kind !== NodeKind.GroupNode) {
                const exposure_filter = seriesToFilterLegacy(exposureSeries, featureFlagKey, variantKey)
                if (exposure_filter) {
                    filters.push(exposure_filter)
                }
            }
        } else {
            filters.push({
                id: EXPOSURE_DEFAULT_EVENT,
                name: EXPOSURE_DEFAULT_EVENT,
                type: 'events',
                properties: [
                    {
                        key: EXPOSURE_FEATURE_FLAG_RESPONSE_PROPERTY,
                        type: PropertyFilterType.Event,
                        value: [variantKey],
                        operator: PropertyOperator.Exact,
                    },
                    {
                        key: EXPOSURE_FEATURE_FLAG_PROPERTY,
                        type: PropertyFilterType.Event,
                        value: featureFlagKey,
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        }
        const countSeries = metric.count_query.series[0]
        // Experiments don't support GroupNode yet - skip if it's a group
        if (countSeries.kind !== NodeKind.GroupNode) {
            const count_filter = seriesToFilterLegacy(countSeries, featureFlagKey, variantKey)
            if (count_filter) {
                filters.push(count_filter)
            }
        }
        return filters
    }
    metric.funnels_query.series.forEach((series) => {
        const filter = seriesToFilterLegacy(series, featureFlagKey, variantKey)
        if (filter) {
            filters.push(filter)
        }
    })
    return filters
}

// Mirrors the backend eligibility rule (experiment_eligibility_error): multivariate with 2-20 variants
export function featureFlagEligibleForExperiment(featureFlag: FeatureFlagType): true {
    const variants = getFlagVariants(featureFlag)
    if (variants.length < 2) {
        throw new Error('Feature flag must have at least 2 variants (a baseline and at least one test variant).')
    }
    if (variants.length > MAX_EXPERIMENT_VARIANTS) {
        throw new Error(`Feature flag must have at most ${MAX_EXPERIMENT_VARIANTS} variants.`)
    }
    return true
}

/**
 * TODO: review. Probably deprecated
 */
export function getDefaultTrendsMetric(): ExperimentTrendsQuery {
    return {
        kind: NodeKind.ExperimentTrendsQuery,
        uuid: uuid(),
        count_query: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: '$pageview',
                    event: '$pageview',
                },
            ],
            interval: 'day',
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
            },
            filterTestAccounts: true,
        },
    }
}

export function getDefaultFunnelsMetric(): ExperimentFunnelsQuery {
    return {
        kind: NodeKind.ExperimentFunnelsQuery,
        uuid: uuid(),
        funnels_query: {
            kind: NodeKind.FunnelsQuery,
            filterTestAccounts: true,
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
            ],
            funnelsFilter: {
                funnelVizType: FunnelVizType.Steps,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                funnelWindowInterval: 14,
                layout: FunnelLayout.horizontal,
            },
        },
    }
}

/**
 * TODO: review. Probably deprecated
 */
export function getDefaultFunnelMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: uuid(),
        metric_type: ExperimentMetricType.FUNNEL,
        goal: ExperimentMetricGoal.Increase,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        ],
    }
}

/**
 * @deprecated
 */
export function getDefaultCountMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: uuid(),
        metric_type: ExperimentMetricType.MEAN,
        goal: ExperimentMetricGoal.Increase,
        source: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
    }
}

export function getDefaultRatioMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: uuid(),
        metric_type: ExperimentMetricType.RATIO,
        goal: ExperimentMetricGoal.Increase,
        numerator: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
        denominator: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
    }
}

export function getDefaultRetentionMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: uuid(),
        metric_type: ExperimentMetricType.RETENTION,
        goal: ExperimentMetricGoal.Increase,
        start_event: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
        completion_event: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
        retention_window_start: 1,
        retention_window_end: 1,
        retention_window_unit: FunnelConversionWindowTimeUnit.Day,
        start_handling: 'first_seen',
    }
}

export function getDefaultExperimentMetric(metricType: ExperimentMetricType): ExperimentMetric {
    switch (metricType) {
        case ExperimentMetricType.FUNNEL:
            return getDefaultFunnelMetric()
        case ExperimentMetricType.RATIO:
            return getDefaultRatioMetric()
        case ExperimentMetricType.RETENTION:
            return getDefaultRetentionMetric()
        default:
            return getDefaultCountMetric()
    }
}

export function getExperimentMetricFromInsight(insight: QueryBasedInsightModel | null): ExperimentMetric | undefined {
    if (!insight?.query || !isValidQueryForExperiment(insight?.query) || !isNodeWithSource(insight.query)) {
        return undefined
    }

    const metricName = (insight?.name || insight?.derived_name) ?? undefined

    if (isFunnelsQuery(insight.query.source)) {
        return {
            kind: NodeKind.ExperimentMetric,
            uuid: uuid(),
            metric_type: ExperimentMetricType.FUNNEL,
            goal: ExperimentMetricGoal.Increase,
            name: metricName,
            series: insight.query.source.series.map((series) => ({
                ...series,
                // Ensure we have proper node structure
                kind: series.kind || NodeKind.EventsNode,
                event: series.kind === NodeKind.EventsNode ? series.event : undefined,
                name: series.name || (series.kind === NodeKind.EventsNode ? series.event : undefined),
            })) as ExperimentFunnelMetricStep[],
        }
    }

    /**
     * TODO: add support for trends queries. IsValidQueryForExperiment
     * has a isFunnelsQuery check, so this is never called. Trend queries
     * get undefined.
     */
    if (isTrendsQuery(insight.query.source)) {
        // For trends queries, convert the first series to a mean metric
        const firstSeries = insight.query.source.series?.[0]
        if (!firstSeries) {
            return undefined
        }

        return {
            kind: NodeKind.ExperimentMetric,
            uuid: uuid(),
            metric_type: ExperimentMetricType.MEAN,
            goal: ExperimentMetricGoal.Increase,
            name: metricName,
            source: {
                ...firstSeries,
                kind: NodeKind.EventsNode,
                event: firstSeries.name,
                name: firstSeries.name,
                math: firstSeries.math || ExperimentMetricMathType.TotalCount,
            },
        }
    }

    return undefined
}

/**
 * Used when setting a custom exposure criteria
 */
export function exposureConfigToFilter(exposure_config: ExperimentExposureConfig): FilterType {
    if (exposure_config.kind === NodeKind.ExperimentEventExposureConfig) {
        return {
            events: [
                {
                    id: exposure_config.event,
                    name: exposure_config.event,
                    kind: NodeKind.EventsNode,
                    type: 'events',
                    properties: exposure_config.properties,
                } as EventsNode,
            ],
            actions: [],
            data_warehouse: [],
        }
    }
    if (exposure_config.kind === NodeKind.ActionsNode) {
        return {
            events: [],
            actions: [
                {
                    id: exposure_config.id,
                    name: exposure_config.name || '',
                    kind: NodeKind.ActionsNode,
                    type: 'actions' as const,
                    properties: exposure_config.properties,
                },
            ],
            data_warehouse: [],
        }
    }

    return {}
}

/**
 * Used when setting a custom exposure criteria
 */
export function filterToExposureConfig(entity: Record<string, any> | undefined): ExperimentExposureConfig | undefined {
    if (!entity) {
        return undefined
    }

    // Check type first since ActionFilter may set kind incorrectly
    if (entity.type === 'actions') {
        return {
            kind: NodeKind.ActionsNode,
            id: entity.id,
            name: entity.name,
            properties: entity.properties,
        }
    }

    if (entity.type === 'events' || entity.kind === NodeKind.EventsNode) {
        return {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: entity.id,
            properties: entity.properties,
        }
    }

    return undefined
}

/**
 * returns the math availability for a metric type
 */
export function getMathAvailability(metricType: ExperimentMetricType): MathAvailability {
    switch (metricType) {
        case ExperimentMetricType.MEAN:
        case ExperimentMetricType.RATIO:
            return MathAvailability.All
        default:
            return MathAvailability.None
    }
}

/**
 * returns the allowed math types that can be used when creating a metric
 */
export function getAllowedMathTypes(metricType: ExperimentMetricType): ExperimentMetricMathType[] {
    switch (metricType) {
        case ExperimentMetricType.MEAN:
            return [
                ExperimentMetricMathType.TotalCount,
                ExperimentMetricMathType.Sum,
                ExperimentMetricMathType.UniqueUsers,
                ExperimentMetricMathType.UniqueGroup,
                ExperimentMetricMathType.Avg,
                ExperimentMetricMathType.Min,
                ExperimentMetricMathType.Max,
                ExperimentMetricMathType.UniqueSessions,
                ExperimentMetricMathType.HogQL,
            ]
        case ExperimentMetricType.RATIO:
            return [
                ExperimentMetricMathType.TotalCount,
                ExperimentMetricMathType.Sum,
                ExperimentMetricMathType.UniqueUsers,
                ExperimentMetricMathType.UniqueGroup,
                ExperimentMetricMathType.UniqueSessions,
                ExperimentMetricMathType.Avg,
                ExperimentMetricMathType.Min,
                ExperimentMetricMathType.Max,
            ]
        default:
            return [ExperimentMetricMathType.TotalCount]
    }
}

/**
 * Check if a query is a legacy experiment metric.
 *
 * We use `unknown` here because in some cases, the query is not typed.
 */
export const isLegacyExperimentQuery = (query: unknown): query is ExperimentTrendsQuery | ExperimentFunnelsQuery => {
    /**
     * since query could be an object literal type, we need to check for the kind property
     */
    return (
        !!query &&
        typeof query === 'object' &&
        'kind' in query &&
        (query.kind === NodeKind.ExperimentTrendsQuery || query.kind === NodeKind.ExperimentFunnelsQuery)
    )
}

/**
 * The legacy query runner uses ExperimentTrendsQuery and ExperimentFunnelsQuery
 * to run experiments.
 *
 * We should remove these legacy metrics once we've migrated all experiments to the new query runner.
 */
export const isLegacyExperiment = (experiment?: Experiment | null): boolean => {
    if (!experiment) {
        return false
    }
    const { metrics, metrics_secondary, saved_metrics } = experiment
    // saved_metrics has a different structure and so we need to check for it separately
    if ((saved_metrics ?? []).some(isLegacySharedMetric)) {
        return true
    }
    return [...(metrics ?? []), ...(metrics_secondary ?? [])].some(isLegacyExperimentQuery)
}

export const isLegacySharedMetric = ({ query }: SharedMetric): boolean => isLegacyExperimentQuery(query)

const getEventCountSeries = (metric: ExperimentMetric): AnyEntityNode[] => {
    /**
     * we short circuit for funnel metrics
     */
    if (isExperimentFunnelMetric(metric)) {
        const lastStep = metric.series[metric.series.length - 1]
        if (lastStep) {
            if (lastStep.kind === NodeKind.EventsNode) {
                return [
                    {
                        kind: NodeKind.EventsNode,
                        name: lastStep.event || undefined,
                        event: lastStep.event,
                        math: ExperimentMetricMathType.TotalCount,
                        ...(lastStep.properties &&
                            lastStep.properties.length > 0 && { properties: lastStep.properties }),
                    },
                ]
            } else if (lastStep.kind === NodeKind.ActionsNode) {
                return [
                    {
                        kind: NodeKind.ActionsNode,
                        id: lastStep.id,
                        name: lastStep.name,
                        math: ExperimentMetricMathType.TotalCount,
                        ...(lastStep.properties &&
                            lastStep.properties.length > 0 && { properties: lastStep.properties }),
                    },
                ]
            }
        }
    }

    const source: ExperimentMetricSource | null = match(metric)
        .when(isExperimentRatioMetric, (ratioMetric) => ratioMetric.numerator)
        .when(isExperimentRetentionMetric, (retentionMetric) => retentionMetric.start_event)
        .when(isExperimentMeanMetric, (meanMetric) => meanMetric.source)
        .otherwise(() => null)

    if (!source) {
        return []
    }

    const series: AnyEntityNode[] = match(source)
        .with({ kind: NodeKind.EventsNode }, (eventsNode) => [
            {
                kind: NodeKind.EventsNode as const,
                name: eventsNode.event || undefined,
                event: eventsNode.event || undefined,
                math: ExperimentMetricMathType.TotalCount,
                ...(eventsNode.properties && eventsNode.properties.length > 0 && { properties: eventsNode.properties }),
            },
        ])
        .with({ kind: NodeKind.ActionsNode }, (actionsNode) => [
            {
                kind: NodeKind.ActionsNode as const,
                id: actionsNode.id,
                name: actionsNode.name,
                math: ExperimentMetricMathType.TotalCount,
                ...(actionsNode.properties &&
                    actionsNode.properties.length > 0 && { properties: actionsNode.properties }),
            },
        ])
        .with({ kind: NodeKind.ExperimentDataWarehouseNode }, (dataWarehouseNode) => [
            {
                kind: NodeKind.DataWarehouseNode as const,
                id: dataWarehouseNode.table_name,
                id_field: dataWarehouseNode.data_warehouse_join_key,
                table_name: dataWarehouseNode.table_name,
                timestamp_field: dataWarehouseNode.timestamp_field,
                distinct_id_field: dataWarehouseNode.events_join_key,
                name: dataWarehouseNode.name,
                math: ExperimentMetricMathType.TotalCount,
                ...(dataWarehouseNode.properties &&
                    dataWarehouseNode.properties.length > 0 && { properties: dataWarehouseNode.properties }),
            },
        ])
        .exhaustive()

    return series
}

/**
 * Builds a TrendsQuery for counting events in the last 14 days for experiment metric preview
 */
export function getEventCountQuery(metric: ExperimentMetric, filterTestAccounts: boolean): TrendsQuery | null {
    const series = getEventCountSeries(metric)

    if (series.length === 0) {
        return null
    }

    // Data warehouse tables don't support test account filters — those filters
    // reference the events table (e.g. events.properties.*), which doesn't exist
    // on a DW table and causes "Unable to resolve field: events". This matches
    // product analytics behavior, where the toggle is disabled for DW sources.
    const isDWQuery = series.some((s) => s.kind === NodeKind.DataWarehouseNode)

    return {
        kind: NodeKind.TrendsQuery,
        series,
        trendsFilter: {
            formulaNodes: [],
            display: ChartDisplayType.BoldNumber,
        },
        dateRange: {
            date_from: '-14d',
            date_to: null,
            explicitDate: false,
        },
        interval: 'day',
        filterTestAccounts: isDWQuery ? false : filterTestAccounts,
        tags: {
            productKey: ProductKey.PRODUCT_ANALYTICS,
        },
    }
}

/**
 * Initialize ordering arrays for metrics if they're null
 * Returns a new experiment object with initialized ordering arrays
 */
export function initializeMetricOrdering(experiment: Experiment): Experiment {
    const newExperiment = { ...experiment }

    // Initialize primary_metrics_ordered_uuids if it's null
    if (newExperiment.primary_metrics_ordered_uuids === null) {
        const primaryMetrics = newExperiment.metrics || []
        const sharedPrimaryMetrics = (newExperiment.saved_metrics || []).filter(
            (sharedMetric: any) => sharedMetric.metadata.type === 'primary'
        )

        const allMetrics = [...primaryMetrics, ...sharedPrimaryMetrics]
        newExperiment.primary_metrics_ordered_uuids = allMetrics
            .map((metric: any) => metric.uuid || metric.query?.uuid)
            .filter(Boolean)
    }

    // Initialize secondary_metrics_ordered_uuids if it's null
    if (newExperiment.secondary_metrics_ordered_uuids === null) {
        const secondaryMetrics = newExperiment.metrics_secondary || []
        const sharedSecondaryMetrics = (newExperiment.saved_metrics || []).filter(
            (sharedMetric: any) => sharedMetric.metadata.type === 'secondary'
        )

        const allMetrics = [...secondaryMetrics, ...sharedSecondaryMetrics]
        newExperiment.secondary_metrics_ordered_uuids = allMetrics
            .map((metric: any) => metric.uuid || metric.query?.uuid)
            .filter(Boolean)
    }

    return newExperiment
}

/**
 * Maps metrics to their results and errors in the correct display order
 * This handles the complex logic of:
 * 1. Mapping results by index to original metrics array (including shared metrics)
 * 2. Enriching shared metrics with metadata, including breakdowns
 * 3. Reordering everything according to the ordered UUIDs
 */
export function getOrderedMetricsWithResults(
    experiment: Experiment,
    primaryMetricsResults: CachedNewExperimentQueryResponse[],
    primaryMetricsResultsErrors: any[],
    secondaryMetricsResults: CachedNewExperimentQueryResponse[],
    secondaryMetricsResultsErrors: any[],
    isSecondary: boolean
): Array<{
    metric: ExperimentMetric
    result: any
    error: any
    displayIndex: number
    metricIndex: number
}> {
    const metricType = isSecondary ? 'secondary' : 'primary'
    const results = isSecondary ? secondaryMetricsResults : primaryMetricsResults
    const errors = isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors

    // Build enriched metrics in original order (same order as results arrays)
    const regularMetrics = isSecondary
        ? ((experiment.metrics_secondary || []) as ExperimentMetric[])
        : ((experiment.metrics || []) as ExperimentMetric[])

    const enrichedSharedMetrics = (experiment.saved_metrics || [])
        .filter((sharedMetric) => sharedMetric.metadata?.type === metricType)
        .map((sharedMetric) => ({
            ...sharedMetric.query,
            name: sharedMetric.name,
            sharedMetricId: sharedMetric.saved_metric,
            isSharedMetric: true,
            /**
             * Merge per-experiment breakdown attribution from metadata into the query
             */
            ...(sharedMetric.metadata?.breakdownAttributionType !== undefined && {
                breakdownAttributionType: sharedMetric.metadata.breakdownAttributionType,
                breakdownAttributionValue: sharedMetric.metadata.breakdownAttributionValue,
            }),
            /**
             * Merge breakdowns from metadata into breakdownFilter
             */
            breakdownFilter: {
                ...sharedMetric.query?.breakdownFilter,
                breakdowns: sharedMetric.metadata?.breakdowns || [],
                ...(sharedMetric.metadata?.breakdown_limit !== undefined && {
                    breakdown_limit: sharedMetric.metadata.breakdown_limit,
                }),
            },
        })) as ExperimentMetric[]

    const allMetrics = [...regularMetrics, ...enrichedSharedMetrics]

    // Create UUID maps in one pass
    const resultsMap = new Map()
    const errorsMap = new Map()
    const metricsMap = new Map()
    const originalIndexMap = new Map()

    allMetrics.forEach((metric: any, index) => {
        const uuid = metric.uuid || metric.query?.uuid
        if (uuid) {
            resultsMap.set(uuid, results[index])
            errorsMap.set(uuid, errors[index])
            metricsMap.set(uuid, metric)
            originalIndexMap.set(uuid, index) // Track original position for retry
        }
    })

    // Get display order and map to final result
    const orderedUuids = isSecondary
        ? experiment.secondary_metrics_ordered_uuids || []
        : experiment.primary_metrics_ordered_uuids || []

    return orderedUuids
        .map((uuid) => metricsMap.get(uuid))
        .filter(Boolean)
        .map((metric: ExperimentMetric, index: number) => ({
            metric,
            result: resultsMap.get(metric.uuid),
            error: errorsMap.get(metric.uuid),
            displayIndex: index,
            metricIndex: originalIndexMap.get(metric.uuid) ?? index, // Original position for retry
        }))
}

export type MetricWithResult = {
    metric: ExperimentMetric
    result: CachedNewExperimentQueryResponse | undefined
    error: unknown
    displayIndex: number
    metricIndex: number
}

/**
 * Narrows to a real, saved experiment: present and not the "new"/draft sentinel id. Used by the
 * recalculation-flow component wrappers before mounting experiment-keyed child logics.
 */
export const isSavedExperiment = (experiment: Experiment | null | undefined): experiment is Experiment =>
    experiment?.id != null && experiment.id !== 'new'

export type ExperimentWritePayload<T> = Omit<T, 'feature_flag' | 'feature_flag_config'> & {
    feature_flag?: ExperimentFeatureFlagInputApi
}

/** Update payload for the experiment API: flag config travels in the write shape. An echoed
 * read-only flag is also accepted — the backend ignores flag objects carrying a non-null id. */
export type ExperimentUpdatePayload = Omit<Partial<Experiment>, 'feature_flag'> & {
    feature_flag?: ExperimentFeatureFlagInputApi | Experiment['feature_flag']
    update_feature_flag_params?: boolean
    original_experiment?: Record<string, any>
}

/** The scalar fields experiment surfaces PATCH, sent as base values so the server can three-way
 * merge them per field: a stale write only conflicts when the same field changed on both sides. */
const CONCURRENCY_SCALAR_BASE_FIELDS = [
    'name',
    'description',
    'start_date',
    'end_date',
    'exposure_criteria',
    'stats_config',
    'running_time_calculation',
    'holdout_id',
    'conclusion',
    'conclusion_comment',
    'excluded_variants',
    'only_count_matured_users',
    'parameters',
] as const

/** Concurrency context for experiment PATCHes: the version last read plus the state that version
 * belongs to (metric collections and scalar bases), so the server can merge concurrent edits per
 * metric uuid / per field and reject only true same-field conflicts with a 409, instead of letting
 * a stale write clobber them. */
export function toConcurrencyPayload(
    unmodified: Experiment | null
): Pick<ExperimentUpdatePayload, 'version' | 'original_experiment'> {
    if (!unmodified || typeof unmodified.id !== 'number') {
        return {}
    }
    return {
        version: unmodified.version ?? 0,
        original_experiment: {
            metrics: unmodified.metrics,
            metrics_secondary: unmodified.metrics_secondary,
            saved_metrics_ids: (unmodified.saved_metrics || []).map((sharedMetric) => ({
                id: sharedMetric.saved_metric,
                metadata: sharedMetric.metadata,
            })),
            // Explicit null over undefined: a missing base key makes the server fall back to
            // rejecting any change to that field, while null means "the field was empty".
            ...Object.fromEntries(CONCURRENCY_SCALAR_BASE_FIELDS.map((field) => [field, unmodified[field] ?? null])),
        },
    }
}

/** Whether an API error is the experiment concurrency conflict (as opposed to any other 409,
 * e.g. an approval-required response, which carries no `current_version`). */
export function isExperimentConflictError(error: any): boolean {
    return error?.status === 409 && error?.data?.current_version !== undefined
}

const CONFLICT_UNPRESERVABLE_KEYS = new Set([
    'metrics',
    'metrics_secondary',
    'saved_metrics_ids',
    'primary_metrics_ordered_uuids',
    'secondary_metrics_ordered_uuids',
    'version',
    'original_experiment',
    'update_feature_flag_params',
    'feature_flag',
])

/** The fields of a 409-rejected update worth keeping in local state: the user's scalar edits.
 * Collection and bookkeeping fields are dropped — re-applying a stale metric array over the
 * fresh state would reintroduce exactly the clobbering the conflict prevented. */
export function conflictPreservedFields(payload: ExperimentUpdatePayload): Partial<Experiment> {
    return Object.fromEntries(Object.entries(payload).filter(([key]) => !CONFLICT_UNPRESERVABLE_KEYS.has(key)))
}

/** Maps UI variants to the flag's write shape, dropping null names the generated type disallows. */
export function toFlagVariantsInput(
    variants: MultivariateFlagVariant[]
): NonNullable<ExperimentFeatureFlagFiltersApi['multivariate']>['variants'] {
    return variants.map(({ key, name, rollout_percentage }) => ({
        key,
        ...(name != null ? { name } : {}),
        rollout_percentage,
    }))
}

/**
 * Builds an experiment write payload. Draft flag config lives on `feature_flag_config` in the
 * flag's own input shape; it moves to the `feature_flag` write field. The read-only `feature_flag`
 * echoed by a GET response is dropped, and `feature_flag_config` never travels literally.
 *
 * Pass `omitFlagConfig` when the experiment links to a pre-existing flag: the flag is linked
 * as-is, and the API rejects explicit config for it.
 */
export function toExperimentWritePayload<T extends Pick<Experiment, 'feature_flag_config'>>(
    experiment: T,
    { omitFlagConfig = false }: { omitFlagConfig?: boolean } = {}
): ExperimentWritePayload<T> {
    const {
        feature_flag: _echoedFlag,
        feature_flag_config,
        ...rest
    } = experiment as T & { feature_flag?: unknown; feature_flag_config?: ExperimentFeatureFlagInputApi }
    const payload = { ...rest } as ExperimentWritePayload<T>

    if (!omitFlagConfig && feature_flag_config) {
        payload.feature_flag = feature_flag_config
    }
    return payload
}

/**
 * Pure zip of one metric type (`primary` | `secondary`) with its results and errors, in display order.
 * Same shaping as {@link getOrderedMetricsWithResults} but curried over the experiment, so a caller can
 * bind it once per experiment instance and reuse it for both primary and secondary:
 *
 *   const zip = metricResults(experiment)
 *   const primary = zip(primaryResults, primaryErrors, 'primary')
 *   const secondary = zip(secondaryResults, secondaryErrors, 'secondary')
 *
 * Used by the recalculation flow; the legacy per-metric path keeps using getOrderedMetricsWithResults.
 */
export const metricResults =
    (experiment: Experiment) =>
    (
        results: CachedNewExperimentQueryResponse[],
        errors: unknown[],
        type: 'primary' | 'secondary'
    ): MetricWithResult[] => {
        const regularMetrics = (
            type === 'secondary' ? experiment.metrics_secondary || [] : experiment.metrics || []
        ) as ExperimentMetric[]

        /**
         * Reshape saved/shared metrics into the inline ExperimentMetric shape so both can be merged and
         * ordered together below.
         */
        const sharedMetrics = (experiment.saved_metrics || [])
            .filter((sharedMetric) => sharedMetric.metadata?.type === type)
            .map((sharedMetric) => ({
                ...sharedMetric.query,
                name: sharedMetric.name,
                sharedMetricId: sharedMetric.saved_metric,
                isSharedMetric: true,
                /**
                 * Merge per-experiment breakdown attribution from metadata into the query
                 */
                ...(sharedMetric.metadata?.breakdownAttributionType !== undefined && {
                    breakdownAttributionType: sharedMetric.metadata.breakdownAttributionType,
                    breakdownAttributionValue: sharedMetric.metadata.breakdownAttributionValue,
                }),
                /**
                 * Merge breakdowns from metadata into breakdownFilter
                 */
                breakdownFilter: {
                    ...sharedMetric.query?.breakdownFilter,
                    breakdowns: sharedMetric.metadata?.breakdowns || [],
                    ...(sharedMetric.metadata?.breakdown_limit !== undefined && {
                        breakdown_limit: sharedMetric.metadata.breakdown_limit,
                    }),
                },
            })) as ExperimentMetric[]

        /**
         * Merge inline + shared metrics, dropping any without a uuid (defensive). One entry per metric
         * carries everything the output row needs, keyed by uuid for the ordering pass below.
         */
        const byUuid = new Map(
            [...regularMetrics, ...sharedMetrics]
                .map((metric, index) => ({ metric, result: results[index], error: errors[index], index }))
                .filter((entry): entry is { metric: ExperimentMetric & { uuid: string } } & typeof entry =>
                    Boolean(entry.metric.uuid)
                )
                .map((entry) => [entry.metric.uuid, entry])
        )

        const orderedUuids =
            type === 'secondary'
                ? experiment.secondary_metrics_ordered_uuids || []
                : experiment.primary_metrics_ordered_uuids || []

        return orderedUuids
            .map((uuid) => byUuid.get(uuid))
            .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry))
            .map(({ metric, result, error, index }, displayIndex) => ({
                metric,
                result,
                error,
                displayIndex,
                metricIndex: index,
            }))
    }
