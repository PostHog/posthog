import { FunnelLayout } from 'lib/constants'

import { hiddenLegendItemsToKeys, queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import {
    FunnelsQuery,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelPathType,
    FunnelStepReference,
    FunnelVizType,
    FunnelsFilterType,
    InsightType,
    LifecycleFilterType,
    PathType,
    PathsFilterType,
    StepOrderValue,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

describe('queryNodeToFilter', () => {
    test('converts a query node to a filter', () => {
        const query: LifecycleQuery = {
            kind: NodeKind.LifecycleQuery,
            lifecycleFilter: {
                toggledLifecycles: ['new', 'dormant'],
            },
            series: [],
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<LifecycleFilterType> = {
            entity_type: 'events',
            insight: InsightType.LIFECYCLE,
            toggledLifecycles: ['new', 'dormant'],
        }
        expect(result).toEqual(filters)
    })

    test('converts a breakdownFilter into breakdown properties', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [],
            breakdownFilter: {
                breakdown: '$current_url',
                breakdown_normalize_url: false,
                breakdown_hide_other_aggregation: false,
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<TrendsFilterType> = {
            entity_type: 'events',
            insight: InsightType.TRENDS,
            breakdown: '$current_url',
            breakdown_hide_other_aggregation: false,
            breakdown_normalize_url: false,
        }
        expect(result).toEqual(filters)
    })

    test('converts a trendsFilter into filter properties', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [],
            breakdownFilter: {
                breakdown: '$browser',
                breakdown_hide_other_aggregation: true,
                breakdown_limit: 1,
                breakdown_type: 'event',
                breakdown_histogram_bin_count: 5,
            },
            trendsFilter: {
                smoothingIntervals: 3,
                formula: 'A + B',
                display: ChartDisplayType.ActionsBar,
                showLegend: true,
                aggregationAxisFormat: 'numeric',
                aggregationAxisPrefix: 'M',
                aggregationAxisPostfix: '$',
                decimalPlaces: 5,
                showValuesOnSeries: true,
                showLabelsOnSeries: true,
                showPercentStackView: true,
                yAxisScaleType: 'log10',
                showMultipleYAxes: false,
                hiddenLegendIndexes: [1, 2],
            },
            compareFilter: {
                compare: true,
                compare_to: '-4d',
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<TrendsFilterType> = {
            insight: InsightType.TRENDS,
            entity_type: 'events',
            hidden_legend_keys: { 1: true, 2: true },
            interval: undefined,
            smoothing_intervals: 3,
            display: ChartDisplayType.ActionsBar,
            formula: 'A + B',
            compare: true,
            compare_to: '-4d',
            decimal_places: 5,
            aggregation_axis_format: 'numeric',
            aggregation_axis_prefix: 'M',
            aggregation_axis_postfix: '$',
            breakdown: '$browser',
            breakdown_hide_other_aggregation: true,
            breakdown_limit: 1,
            breakdown_type: 'event',
            breakdown_histogram_bin_count: 5,
            show_labels_on_series: true,
            show_percent_stack_view: true,
            show_legend: true,
            show_values_on_series: true,
            y_axis_scale_type: 'log10',
            show_multiple_y_axes: false,
        }
        expect(result).toEqual(filters)
    })

    test('converts a funnelsFilter into filter properties', () => {
        const query: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            funnelsFilter: {
                funnelVizType: FunnelVizType.Steps,
                funnelFromStep: 1,
                funnelToStep: 2,
                funnelStepReference: FunnelStepReference.total,
                breakdownAttributionType: BreakdownAttributionType.AllSteps,
                breakdownAttributionValue: 1,
                binCount: 'auto',
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                funnelWindowInterval: 7,
                funnelOrderType: StepOrderValue.ORDERED,
                exclusions: [
                    {
                        event: '$pageview',
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        funnelFromStep: 1,
                        funnelToStep: 2,
                    },
                    {
                        id: 3,
                        kind: NodeKind.ActionsNode,
                        name: 'Some action',
                        funnelFromStep: 1,
                        funnelToStep: 2,
                    },
                ],
                layout: FunnelLayout.horizontal,
            },
            series: [],
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<FunnelsFilterType> = {
            insight: InsightType.FUNNELS,
            funnel_viz_type: FunnelVizType.Steps,
            funnel_from_step: 1,
            funnel_to_step: 2,
            funnel_step_reference: FunnelStepReference.total,
            breakdown_attribution_type: BreakdownAttributionType.AllSteps,
            breakdown_attribution_value: 1,
            bin_count: 'auto',
            funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
            funnel_window_interval: 7,
            funnel_order_type: StepOrderValue.ORDERED,
            exclusions: [
                {
                    id: '$pageview',
                    type: 'events',
                    order: 0,
                    name: '$pageview',
                    funnel_from_step: 1,
                    funnel_to_step: 2,
                },
                {
                    id: 3,
                    type: 'actions',
                    order: 1,
                    name: 'Some action',
                    funnel_from_step: 1,
                    funnel_to_step: 2,
                },
            ],
            layout: FunnelLayout.horizontal,
            interval: undefined,
            hidden_legend_keys: undefined,
            funnel_aggregate_by_hogql: undefined,
            entity_type: 'events',
        }
        expect(result).toEqual(filters)
    })

    test('converts a pathsFilter and funnelPathsFilter into filter properties', () => {
        const query: PathsQuery = {
            kind: NodeKind.PathsQuery,
            pathsFilter: {
                includeEventTypes: [PathType.Screen, PathType.PageView],
                startPoint: 'a',
                endPoint: 'b',
                pathGroupings: ['c', 'd'],
                excludeEvents: ['e', 'f'],
                stepLimit: 1,
                pathReplacements: true,
                localPathCleaningFilters: [{ alias: 'home' }],
                edgeLimit: 1,
                minEdgeWeight: 1,
                maxEdgeWeight: 1,
            },
            funnelPathsFilter: {
                funnelPathType: FunnelPathType.between,
                funnelStep: 1,
                funnelSource: {
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.Steps,
                    },
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        {
                            event: '$pageview',
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                        },
                        {
                            event: null,
                            kind: NodeKind.EventsNode,
                        },
                    ],
                },
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<PathsFilterType> = {
            insight: InsightType.PATHS,
            include_event_types: [PathType.Screen, PathType.PageView],
            start_point: 'a',
            end_point: 'b',
            path_groupings: ['c', 'd'],
            funnel_paths: FunnelPathType.between,
            entity_type: 'events',
            funnel_filter: {
                entity_type: 'events',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        order: 0,
                        type: 'events',
                    },
                    {
                        id: null,
                        order: 1,
                        type: 'events',
                    },
                ],
                exclusions: undefined,
                funnel_step: 1,
                funnel_viz_type: 'steps',
                insight: 'FUNNELS',
                bin_count: undefined,
                breakdown_attribution_type: undefined,
                breakdown_attribution_value: undefined,
                funnel_aggregate_by_hogql: undefined,
                funnel_from_step: undefined,
                funnel_to_step: undefined,
                funnel_order_type: undefined,
                funnel_step_reference: undefined,
                funnel_window_interval: undefined,
                funnel_window_interval_unit: undefined,
                hidden_legend_keys: undefined,
                interval: undefined,
            },
            exclude_events: ['e', 'f'],
            step_limit: 1,
            // path_start_key: 'g',
            // path_end_key: 'h',
            // path_dropoff_key: 'i',
            path_replacements: true,
            local_path_cleaning_filters: [{ alias: 'home' }],
            edge_limit: 1,
            min_edge_weight: 1,
            max_edge_weight: 1,
            paths_hogql_expression: undefined,
        }
        expect(result).toEqual(filters)
    })

    test('converts a stickinessFilter into filter properties', () => {
        const query: StickinessQuery = {
            kind: NodeKind.StickinessQuery,
            stickinessFilter: {
                display: ChartDisplayType.ActionsBar,
                showLegend: true,
                showValuesOnSeries: true,
                hiddenLegendIndexes: [1, 2],
            },
            interval: 'month',
            series: [],
            compareFilter: {
                compare: true,
                compare_to: '-4d',
            },
        }

        const result = queryNodeToFilter(query)

        const filters: Partial<StickinessFilterType> = {
            insight: InsightType.STICKINESS,
            compare: true,
            compare_to: '-4d',
            display: ChartDisplayType.ActionsBar,
            hidden_legend_keys: { 1: true, 2: true },
            interval: 'month',
            show_legend: true,
            show_values_on_series: true,
            entity_type: 'events',
        }
        expect(result).toEqual(filters)
    })
})

describe('hiddenLegendItemsToKeys', () => {
    it('handles undefined', () => {
        expect(hiddenLegendItemsToKeys(undefined)).toEqual(undefined)
    })

    it('converts keys for funnel insights (breakdowns)', () => {
        expect(hiddenLegendItemsToKeys(['a'])).toEqual({ a: true })
        expect(hiddenLegendItemsToKeys(['a', 'b'])).toEqual({ a: true, b: true })
    })

    it('converts keys for trends/stickiness insights', () => {
        expect(hiddenLegendItemsToKeys([1])).toEqual({ '1': true })
        expect(hiddenLegendItemsToKeys([1, 2])).toEqual({ '1': true, '2': true })
    })
})
