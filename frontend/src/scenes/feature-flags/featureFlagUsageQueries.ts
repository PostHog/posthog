// The Usage tab renders these charts inline for flags without a usage dashboard. Event names,
// property keys, breakdown, and math must stay identical to the saved-dashboard insight definitions
// in posthog/helpers/dashboard_templates.py (create_feature_flag_dashboard and
// add_enriched_insights_to_feature_flag_dashboard), so both surfaces report the same numbers.
// Titles differ on purpose: update_feature_flag_dashboard looks tiles up by name, so the Python
// names are pinned, while these use sentence case. The interval here follows the user's date range
// rather than the template's fixed "day".
import { getDefaultInterval } from 'lib/utils/dateFilters'

import { Noun } from '~/models/groupsModel'
import {
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

export interface FlagUsageChart {
    key: string
    title: string
    description: string
    query: InsightVizNode<TrendsQuery>
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

export function buildFlagCalledTotalVolumeChart(options: FlagUsageQueryOptions): FlagUsageChart {
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

export function buildFlagCalledUniqueCallersChart(options: FlagUsageQueryOptions): FlagUsageChart {
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
): FlagUsageChart[] {
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
