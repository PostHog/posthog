// The Usage tab renders these charts inline for flags without a usage dashboard. Event names,
// property keys, breakdown, and math must stay identical to the saved-dashboard insight definitions
// in posthog/helpers/dashboard_templates.py (create_feature_flag_dashboard and
// add_enriched_insights_to_feature_flag_dashboard), so both surfaces report the same numbers.
// Titles differ on purpose: update_feature_flag_dashboard looks tiles up by name, so the Python
// names are pinned, while these use sentence case. The interval here follows the user's date range
// rather than the template's fixed "day".
//
// The buildFlagEvaluations* builders answer the same two questions from the flag_evaluations table
// instead of the events table, for the organizations that read flag evaluations from there.
import { dayjs } from 'lib/dayjs'
import { dateMapping, dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'

import { Noun } from '~/models/groupsModel'
import {
    ChartSettings,
    DataVisualizationNode,
    DateRange,
    EventsNode,
    InsightVizNode,
    NodeKind,
    ProductKey,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    DateMappingOption,
    GroupMathType,
    GroupTypeIndex,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

export interface FlagUsageQueryOptions {
    flagKey: string
    aggregationGroupTypeIndex: number | null | undefined
    /** Noun matching aggregationGroupTypeIndex, e.g. from groupsModel's aggregationLabel(index, true). */
    callerNoun: Noun
    dateRange: DateRange
}

export const DEFAULT_USAGE_DATE_RANGE: DateRange = { date_from: '-30d', date_to: null }

export type FlagUsageQuery = InsightVizNode<TrendsQuery> | DataVisualizationNode

export interface FlagUsageChart<Q extends FlagUsageQuery = FlagUsageQuery> {
    key: string
    title: string
    description: string
    query: Q
}

function flagCalledProperties({ flagKey, aggregationGroupTypeIndex }: FlagUsageQueryOptions): AnyPropertyFilter[] {
    const properties: AnyPropertyFilter[] = [
        {
            key: '$feature_flag',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
            value: flagKey,
        },
    ]
    if (aggregationGroupTypeIndex != null) {
        properties.push({
            key: `$group_${aggregationGroupTypeIndex}`,
            type: PropertyFilterType.Event,
            operator: PropertyOperator.IsSet,
            value: 'is_set',
        })
    }
    return properties
}

function buildUsageQuery(
    dateRange: DateRange,
    source: Pick<TrendsQuery, 'series' | 'properties' | 'breakdownFilter'>,
    display: ChartDisplayType
): InsightVizNode<TrendsQuery> {
    return setLatestVersionsOnQuery({
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            ...source,
            dateRange,
            interval: getDefaultInterval(dateRange.date_from ?? null, dateRange.date_to ?? null),
            filterTestAccounts: false,
            trendsFilter: { display, aggregationAxisFormat: 'numeric' },
            tags: { productKey: ProductKey.FEATURE_FLAGS },
        },
    })
}

export function buildFlagCalledTotalVolumeChart(
    options: FlagUsageQueryOptions
): FlagUsageChart<InsightVizNode<TrendsQuery>> {
    return {
        key: 'total-volume',
        title: 'Feature flag called total volume',
        description: `Shows the number of total calls made on feature flag with key: ${options.flagKey}`,
        query: buildUsageQuery(
            options.dateRange,
            {
                series: [{ kind: NodeKind.EventsNode, event: '$feature_flag_called', name: '$feature_flag_called' }],
                breakdownFilter: { breakdown: '$feature_flag_response', breakdown_type: 'event' },
                properties: flagCalledProperties(options),
            },
            ChartDisplayType.ActionsLineGraph
        ),
    }
}

export function buildFlagCalledUniqueCallersChart(
    options: FlagUsageQueryOptions
): FlagUsageChart<InsightVizNode<TrendsQuery>> {
    const mathProperties: Pick<EventsNode, 'math' | 'math_group_type_index'> =
        options.aggregationGroupTypeIndex != null
            ? {
                  math: GroupMathType.UniqueGroup,
                  math_group_type_index: options.aggregationGroupTypeIndex as GroupTypeIndex,
              }
            : { math: BaseMathType.UniqueUsers }
    return {
        key: 'unique-callers',
        title: `Feature flag calls made by unique ${options.callerNoun.plural} per variant`,
        description: `Shows the number of unique ${options.callerNoun.singular} calls made on feature flag per variant with key: ${options.flagKey}`,
        query: buildUsageQuery(
            options.dateRange,
            {
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$feature_flag_called',
                        name: '$feature_flag_called',
                        ...mathProperties,
                    },
                ],
                breakdownFilter: { breakdown: '$feature_flag_response', breakdown_type: 'event' },
                properties: flagCalledProperties(options),
            },
            ChartDisplayType.ActionsTable
        ),
    }
}

export function buildEnrichedUsageCharts(
    options: Pick<FlagUsageQueryOptions, 'flagKey' | 'dateRange'>
): FlagUsageChart<InsightVizNode<TrendsQuery>>[] {
    return [
        {
            key: 'feature-view',
            title: 'Feature viewed total volume',
            description: 'Shows the total number of times this feature was viewed',
            query: buildUsageQuery(
                options.dateRange,
                {
                    series: enrichedSeries('$feature_view', 'Feature view'),
                    properties: enrichedProperties(options.flagKey),
                },
                ChartDisplayType.ActionsLineGraph
            ),
        },
        {
            key: 'feature-interaction',
            title: 'Feature interaction total volume',
            description: 'Shows the total number of times this feature was interacted with',
            query: buildUsageQuery(
                options.dateRange,
                {
                    series: enrichedSeries('$feature_interaction', 'Feature interaction'),
                    properties: enrichedProperties(options.flagKey),
                },
                ChartDisplayType.ActionsLineGraph
            ),
        },
    ]
}

function enrichedSeries(event: '$feature_view' | '$feature_interaction', seriesLabel: string): EventsNode[] {
    return [
        { kind: NodeKind.EventsNode, event, name: `${seriesLabel} - Total` },
        { kind: NodeKind.EventsNode, event, name: `${seriesLabel} - Unique users`, math: BaseMathType.UniqueUsers },
    ]
}

// The dedicated flag-evaluation table, which only holds $feature_flag_called. It is not a root
// table, so the `posthog.` prefix is part of the name. An organization without the
// flag-evaluations-hogql-table flag has no such table, and these queries fail to resolve for it.
const FLAG_EVALUATIONS_TABLE = 'posthog.flag_evaluations'

/** How long a row stays in flag_evaluations. The events table keeps $feature_flag_called forever. */
export const FLAG_EVALUATIONS_RETENTION_DAYS = 90

/** Start of the oldest day the table still holds. */
function earliestRetainedDay(): dayjs.Dayjs {
    return dayjs().startOf('day').subtract(FLAG_EVALUATIONS_RETENTION_DAYS, 'day')
}

/**
 * Pulls a date range back inside the retention window. A range that reaches further would show
 * fewer rows than the same range on the events table, with nothing on the chart to say why.
 */
export function clampToFlagEvaluationsRetention(dateRange: DateRange): DateRange {
    const earliest = earliestRetainedDay()
    const dateFrom = dateStringToDayJs(dateRange.date_from ?? null)
    // A null start is "all time", which reaches further than any retained day.
    if (dateFrom && !dateFrom.isBefore(earliest)) {
        return dateRange
    }
    const dateTo = dateStringToDayJs(dateRange.date_to ?? null)
    return {
        date_from: `-${FLAG_EVALUATIONS_RETENTION_DAYS}d`,
        // A range that ended before the window holds nothing, and the clamped start would sit
        // after its end. Run to now instead of showing a backwards range.
        date_to: dateTo?.isBefore(earliest) ? null : (dateRange.date_to ?? null),
    }
}

/** The presets that stay inside the retention window, plus the custom-range entry. */
export function flagEvaluationsDateOptions(): DateMappingOption[] {
    const earliest = earliestRetainedDay()
    return dateMapping.filter(({ values }) => {
        const dateFrom = values[0]
        if (dateFrom === undefined) {
            return true
        }
        const parsed = dateStringToDayJs(dateFrom)
        return !!parsed && !parsed.isBefore(earliest)
    })
}

function flagEvaluationsConditions({ aggregationGroupTypeIndex }: FlagUsageQueryOptions): string {
    // `{filters(... AS timestamp)}` binds the tab's date range to this table's own timestamp column.
    // The bare `{filters}` placeholder only knows a fixed set of tables, and this is not one of them.
    const conditions = ['flag_key = {flag_key}', '{filters(timestamp AS timestamp)}']
    if (aggregationGroupTypeIndex != null) {
        // The group columns are non-nullable and hold an empty string when the evaluation
        // carried no group, so this is the equivalent of the events path's is_set filter.
        conditions.push(`\`$group_${aggregationGroupTypeIndex}\` != ''`)
    }
    return conditions.join('\n    AND ')
}

function buildFlagEvaluationsQuery(
    options: FlagUsageQueryOptions,
    query: string,
    display: ChartDisplayType,
    chartSettings?: ChartSettings
): DataVisualizationNode {
    const { dateRange, flagKey } = options
    return setLatestVersionsOnQuery({
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query,
            filters: { dateRange },
            values: { flag_key: flagKey },
        },
        display,
        chartSettings,
    })
}

export function buildFlagEvaluationsTotalVolumeChart(
    options: FlagUsageQueryOptions
): FlagUsageChart<DataVisualizationNode> {
    // dateTrunc needs a literal unit, so the interval is written into the query rather than
    // passed as a value. getDefaultInterval only returns members of IntervalType.
    const interval = getDefaultInterval(options.dateRange.date_from ?? null, options.dateRange.date_to ?? null)
    return {
        key: 'total-volume',
        title: 'Feature flag called total volume',
        description: `Shows the number of total calls made on feature flag with key: ${options.flagKey}`,
        query: buildFlagEvaluationsQuery(
            options,
            `SELECT
    dateTrunc('${interval}', timestamp) AS period,
    response AS variant,
    count() AS total
FROM ${FLAG_EVALUATIONS_TABLE}
WHERE ${flagEvaluationsConditions(options)}
GROUP BY period, variant
ORDER BY period`,
            ChartDisplayType.ActionsLineGraph,
            {
                xAxis: { column: 'period' },
                yAxis: [{ column: 'total' }],
                seriesBreakdownColumn: 'variant',
            }
        ),
    }
}

export function buildFlagEvaluationsUniqueCallersChart(
    options: FlagUsageQueryOptions
): FlagUsageChart<DataVisualizationNode> {
    const { aggregationGroupTypeIndex, callerNoun, flagKey } = options
    // The row keeps the person it was attributed to when the flag was evaluated, and a later
    // identify or merge does not rewrite it, so this count can be higher than the events one.
    const caller = aggregationGroupTypeIndex != null ? `\`$group_${aggregationGroupTypeIndex}\`` : 'person_id'
    return {
        key: 'unique-callers',
        title: `Feature flag calls made by unique ${callerNoun.plural} per variant`,
        description: `Shows the number of unique ${callerNoun.singular} calls made on feature flag per variant with key: ${flagKey}`,
        query: buildFlagEvaluationsQuery(
            options,
            `SELECT
    response AS \`Variant\`,
    uniq(${caller}) AS \`Unique callers\`
FROM ${FLAG_EVALUATIONS_TABLE}
WHERE ${flagEvaluationsConditions(options)}
GROUP BY \`Variant\`
ORDER BY \`Unique callers\` DESC`,
            ChartDisplayType.ActionsTable
        ),
    }
}

// Enriched analytics events carry the flag key in the bare `feature_flag` property,
// unlike $feature_flag_called which uses `$feature_flag`.
function enrichedProperties(flagKey: string): AnyPropertyFilter[] {
    return [
        {
            key: 'feature_flag',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
            value: flagKey,
        },
    ]
}
