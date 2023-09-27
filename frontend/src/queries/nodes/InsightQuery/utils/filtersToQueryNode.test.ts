import { FunnelLayout, ShownAsValue } from 'lib/constants'
import {
    InsightQueryNode,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    StickinessQuery,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
} from '~/queries/schema'
import {
    TrendsFilterType,
    RetentionFilterType,
    FunnelsFilterType,
    PathsFilterType,
    StickinessFilterType,
    LifecycleFilterType,
    ActionFilter,
    BaseMathType,
    ChartDisplayType,
    FilterLogicalOperator,
    FilterType,
    InsightType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    FunnelVizType,
    FunnelStepReference,
    BreakdownAttributionType,
    FunnelConversionWindowTimeUnit,
    StepOrderValue,
    PathType,
    FunnelPathType,
    RetentionPeriod,
    GroupMathType,
} from '~/types'
import {
    actionsAndEventsToSeries,
    cleanHiddenLegendIndexes,
    cleanHiddenLegendSeries,
    filtersToQueryNode,
} from './filtersToQueryNode'

describe('actionsAndEventsToSeries', () => {
    it('sorts series by order', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', order: 1, name: 'item2', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item3' },
        ]

        const result = actionsAndEventsToSeries({ actions, events })

        expect(result[0].name).toEqual('item1')
        expect(result[1].name).toEqual('item2')
        expect(result[2].name).toEqual('item3')
    })

    it('sorts elements without order first', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', name: 'itemWithOrder', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item2' },
        ]

        const result = actionsAndEventsToSeries({ actions, events })

        expect(result[0].name).toEqual('itemWithOrder')
        expect(result[1].name).toEqual('item1')
        expect(result[2].name).toEqual('item2')
    })
})

describe('cleanHiddenLegendIndexes', () => {
    it('converts legend keys', () => {
        const keys: Record<string, boolean | undefined> = {
            1: true,
            2: false,
            3: undefined,
        }

        const result = cleanHiddenLegendIndexes(keys)

        expect(result).toEqual([1])
    })

    it('handles undefined legend keys', () => {
        const keys = undefined

        const result = cleanHiddenLegendIndexes(keys)

        expect(result).toEqual(undefined)
    })

    it('ignores invalid keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            'events/$pageview/0/Baseline': true,
            1: true,
        }

        const result = cleanHiddenLegendIndexes(keys)

        expect(result).toEqual([1])
    })
})

describe('cleanHiddenLegendSeries', () => {
    it('converts legend keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Chrome: true,
            'Chrome iOS': true,
            Firefox: false,
            Safari: undefined,
        }

        const result = cleanHiddenLegendSeries(keys)

        expect(result).toEqual(['Chrome', 'Chrome iOS'])
    })

    it('handles undefined legend keys', () => {
        const keys = undefined

        const result = cleanHiddenLegendSeries(keys)

        expect(result).toEqual(undefined)
    })

    it('converts legacy format', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            'events/$pageview/0/Baseline': true,
            1: true,
        }

        const result = cleanHiddenLegendSeries(keys)

        expect(result).toEqual(['Opera', 'Baseline'])
    })

    it('ignores digit-only keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            1: true,
        }

        const result = cleanHiddenLegendSeries(keys)

        expect(result).toEqual(['Opera'])
    })
})

describe('filtersToQueryNode', () => {
    describe('global filters', () => {
        it('converts test account filter', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.RETENTION,
                filter_test_accounts: true,
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.RetentionQuery,
                filterTestAccounts: true,
            }
            expect(result).toEqual(query)
        })

        it('converts properties', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.RETENTION,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: 'is_set',
                                    operator: PropertyOperator.IsSet,
                                },
                            ],
                        },
                    ],
                },
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.RetentionQuery,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: 'is_set',
                                    operator: PropertyOperator.IsSet,
                                },
                            ],
                        },
                    ],
                },
            }
            expect(result).toEqual(query)
        })

        it('converts date range', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.RETENTION,
                date_to: '2021-12-08',
                date_from: '2021-12-08',
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.RetentionQuery,
                dateRange: {
                    date_to: '2021-12-08',
                    date_from: '2021-12-08',
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('filter with series', () => {
        it('converts series', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    { id: '$pageview', type: 'events', order: 0, name: 'item1' },
                    { id: '$autocapture', type: 'events', order: 2, name: 'item3' },
                ],
                actions: [{ type: 'actions', id: 1, order: 1, name: 'item2', math: 'total' }],
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: 'item1',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.ActionsNode,
                        id: 1,
                        math: BaseMathType.TotalCount,
                        name: 'item2',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: '$autocapture',
                        name: 'item3',
                        math: BaseMathType.TotalCount,
                    },
                ],
            }
            expect(result).toEqual(query)
        })

        it('converts interval', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.TRENDS,
                interval: 'day',
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<TrendsQuery> = {
                kind: NodeKind.TrendsQuery,
                interval: 'day',
            }
            expect(result).toEqual(query)
        })
    })

    describe('trends filter', () => {
        it('converts all properties', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                smoothing_intervals: 1,
                show_legend: true,
                hidden_legend_keys: { 0: true, 10: true },
                compare: true,
                aggregation_axis_format: 'numeric',
                aggregation_axis_prefix: '£',
                aggregation_axis_postfix: '%',
                breakdown_histogram_bin_count: 1,
                formula: 'A+B',
                shown_as: ShownAsValue.VOLUME,
                display: ChartDisplayType.ActionsAreaGraph,
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<TrendsQuery> = {
                kind: NodeKind.TrendsQuery,
                trendsFilter: {
                    smoothing_intervals: 1,
                    show_legend: true,
                    hidden_legend_indexes: [0, 10],
                    compare: true,
                    aggregation_axis_format: 'numeric',
                    aggregation_axis_prefix: '£',
                    aggregation_axis_postfix: '%',
                    formula: 'A+B',
                    shown_as: ShownAsValue.VOLUME,
                    display: ChartDisplayType.ActionsAreaGraph,
                },
                breakdown: {
                    breakdown_histogram_bin_count: 1,
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('funnels filter', () => {
        it('converts all properties', () => {
            const filters: Partial<FunnelsFilterType> = {
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
                funnel_from_step: 1,
                funnel_to_step: 2,
                funnel_step_reference: FunnelStepReference.total,
                funnel_step_breakdown: 1,
                breakdown_attribution_type: BreakdownAttributionType.AllSteps,
                breakdown_attribution_value: 1,
                bin_count: 'auto',
                funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
                funnel_window_interval: 7,
                funnel_order_type: StepOrderValue.ORDERED,
                exclusions: [
                    {
                        funnel_from_step: 0,
                        funnel_to_step: 1,
                    },
                ],
                funnel_correlation_person_entity: { a: 1 },
                funnel_correlation_person_converted: 'true',
                funnel_custom_steps: [1, 2, 3],
                layout: FunnelLayout.horizontal,
                funnel_step: 1,
                entrance_period_start: 'abc',
                drop_off: true,
                hidden_legend_keys: { Chrome: true, Safari: true },
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<FunnelsQuery> = {
                kind: NodeKind.FunnelsQuery,
                funnelsFilter: {
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
                            funnel_from_step: 0,
                            funnel_to_step: 1,
                        },
                    ],
                    layout: FunnelLayout.horizontal,
                    hidden_legend_breakdowns: ['Chrome', 'Safari'],
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('retention filter', () => {
        it('converts all properties', () => {
            const filters: Partial<RetentionFilterType> = {
                insight: InsightType.RETENTION,
                retention_type: 'retention_first_time',
                retention_reference: 'total',
                total_intervals: 2,
                returning_entity: [{ a: 1 }],
                target_entity: [{ b: 1 }],
                period: RetentionPeriod.Day,
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<RetentionQuery> = {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {
                    retention_type: 'retention_first_time',
                    retention_reference: 'total',
                    total_intervals: 2,
                    returning_entity: [{ a: 1 }],
                    target_entity: [{ b: 1 }],
                    period: RetentionPeriod.Day,
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('paths filter', () => {
        it('converts all properties', () => {
            const filters: Partial<PathsFilterType> = {
                insight: InsightType.PATHS,
                path_type: PathType.Screen,
                include_event_types: [PathType.Screen, PathType.PageView],
                start_point: 'a',
                end_point: 'b',
                path_groupings: ['c', 'd'],
                funnel_paths: FunnelPathType.between,
                funnel_filter: { a: 1 },
                exclude_events: ['e', 'f'],
                step_limit: 1,
                path_start_key: 'g',
                path_end_key: 'h',
                path_dropoff_key: 'i',
                path_replacements: true,
                local_path_cleaning_filters: [{ alias: 'home' }],
                edge_limit: 1,
                min_edge_weight: 1,
                max_edge_weight: 1,
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<PathsQuery> = {
                kind: NodeKind.PathsQuery,
                pathsFilter: {
                    path_type: PathType.Screen,
                    include_event_types: [PathType.Screen, PathType.PageView],
                    start_point: 'a',
                    end_point: 'b',
                    path_groupings: ['c', 'd'],
                    funnel_paths: FunnelPathType.between,
                    funnel_filter: { a: 1 },
                    exclude_events: ['e', 'f'],
                    step_limit: 1,
                    path_replacements: true,
                    local_path_cleaning_filters: [{ alias: 'home' }],
                    edge_limit: 1,
                    min_edge_weight: 1,
                    max_edge_weight: 1,
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('stickiness filter', () => {
        it('converts all properties', () => {
            const filters: Partial<StickinessFilterType> = {
                insight: InsightType.STICKINESS,
                compare: true,
                show_legend: true,
                hidden_legend_keys: { 0: true, 10: true },
                shown_as: ShownAsValue.STICKINESS,
                display: ChartDisplayType.ActionsLineGraph,
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<StickinessQuery> = {
                kind: NodeKind.StickinessQuery,
                stickinessFilter: {
                    compare: true,
                    show_legend: true,
                    hidden_legend_indexes: [0, 10],
                    shown_as: ShownAsValue.STICKINESS,
                    display: ChartDisplayType.ActionsLineGraph,
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('lifecycle filter', () => {
        it('converts all properties', () => {
            const filters: Partial<LifecycleFilterType> = {
                insight: InsightType.LIFECYCLE,
                shown_as: ShownAsValue.LIFECYCLE,
                toggledLifecycles: ['new', 'dormant'],
            }

            const result = filtersToQueryNode(filters)

            const query: Partial<LifecycleQuery> = {
                kind: NodeKind.LifecycleQuery,
                lifecycleFilter: {
                    shown_as: ShownAsValue.LIFECYCLE,
                    toggledLifecycles: ['new', 'dormant'],
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('example insights', () => {
        it('converts `New user retention` insight', () => {
            const filters: Partial<RetentionFilterType> = {
                insight: InsightType.RETENTION,
                period: RetentionPeriod.Week,
                // TODO: why does the original example have a display here?
                // display: ChartDisplayType.ActionsTable,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: 'is_set',
                                    operator: PropertyOperator.IsSet,
                                },
                            ],
                        },
                    ],
                },
                target_entity: {
                    id: 'signed_up',
                    name: 'signed_up',
                    type: 'events',
                    order: 0,
                },
                retention_type: 'retention_first_time',
                total_intervals: 9,
                returning_entity: {
                    id: 1,
                    name: 'Interacted with file',
                    type: 'actions',
                    order: 0,
                },
                date_from: '-7d',
            }

            const result = filtersToQueryNode(filters)

            const query: RetentionQuery = {
                kind: NodeKind.RetentionQuery,
                dateRange: {
                    date_from: '-7d',
                },
                retentionFilter: {
                    period: RetentionPeriod.Week,
                    target_entity: {
                        id: 'signed_up',
                        name: 'signed_up',
                        type: 'events',
                        order: 0,
                    },
                    retention_type: 'retention_first_time',
                    total_intervals: 9,
                    returning_entity: {
                        id: 1,
                        name: 'Interacted with file',
                        type: 'actions',
                        order: 0,
                    },
                },
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: 'is_set',
                                    operator: PropertyOperator.IsSet,
                                },
                            ],
                        },
                    ],
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Active user lifecycle` insight', () => {
            const filters: Partial<LifecycleFilterType> = {
                insight: InsightType.LIFECYCLE,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
                filter_test_accounts: true,
                date_from: '-8w',
                entity_type: 'events', // TODO: what does this do?
                actions: [
                    {
                        type: 'actions',
                        id: 1,
                        name: 'Interacted with file',
                        math: 'total',
                    },
                ],
                events: [],
                interval: 'day',
                shown_as: ShownAsValue.LIFECYCLE,
            }

            const result = filtersToQueryNode(filters)

            const query: LifecycleQuery = {
                kind: NodeKind.LifecycleQuery,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
                filterTestAccounts: true,
                dateRange: {
                    date_from: '-8w',
                },
                series: [
                    {
                        kind: NodeKind.ActionsNode,
                        id: 1,
                        name: 'Interacted with file',
                        math: BaseMathType.TotalCount,
                    },
                ],
                interval: 'day',
                lifecycleFilter: {
                    shown_as: ShownAsValue.LIFECYCLE,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Monthly app revenue` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'paid_bill',
                        math: 'sum',
                        type: 'events',
                        order: 0,
                        math_property: 'amount_usd',
                    },
                ],
                actions: [],
                date_from: '-6m',
                interval: 'month',
                display: ChartDisplayType.ActionsLineGraph,
                properties: [],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'paid_bill',
                        math: PropertyMathType.Sum,
                        math_property: 'amount_usd',
                    },
                ],
                dateRange: {
                    date_from: '-6m',
                },
                interval: 'month',
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Bills paid` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'paid_bill',
                        math: 'unique_group',
                        name: 'paid_bill',
                        type: 'events',
                        order: 0,
                        math_group_type_index: 0,
                    },
                ],
                actions: [],
                compare: true,
                date_to: null,
                display: ChartDisplayType.BoldNumber,
                date_from: '-30d',
                properties: [],
                filter_test_accounts: true,
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'paid_bill',
                        name: 'paid_bill',
                        math: GroupMathType.UniqueGroup,
                        math_group_type_index: 0,
                    },
                ],
                dateRange: {
                    date_to: null,
                    date_from: '-30d',
                },
                filterTestAccounts: true,
                trendsFilter: {
                    compare: true,
                    display: ChartDisplayType.BoldNumber,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Daily unique visitors over time` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: '$pageview',
                        math: 'dau',
                        type: 'events',
                        order: 0,
                    },
                ],
                actions: [],
                display: ChartDisplayType.ActionsLineGraph,
                interval: 'day',
                date_from: '-6m',
                properties: [],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        math: BaseMathType.UniqueUsers,
                    },
                ],
                dateRange: {
                    date_from: '-6m',
                },
                interval: 'day',
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Most popular pages` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: '$pageview',
                        math: 'total',
                        type: 'events',
                        order: 0,
                    },
                ],
                actions: [],
                display: ChartDisplayType.ActionsTable,
                breakdown: '$current_url',
                date_from: '-6m',
                new_entity: [],
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: '$current_url',
                                    type: PropertyFilterType.Event,
                                    value: '/files/',
                                    operator: PropertyOperator.NotIContains,
                                },
                            ],
                        },
                    ],
                },
                breakdown_type: 'event',
                breakdown_normalize_url: true,
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        math: BaseMathType.TotalCount,
                    },
                ],
                trendsFilter: {
                    display: ChartDisplayType.ActionsTable,
                },
                breakdown: {
                    breakdown: '$current_url',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                },
                dateRange: {
                    date_from: '-6m',
                },
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: '$current_url',
                                    type: PropertyFilterType.Event,
                                    value: '/files/',
                                    operator: PropertyOperator.NotIContains,
                                },
                            ],
                        },
                    ],
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Weekly signups` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'signed_up',
                        type: 'events',
                        order: 0,
                    },
                ],
                actions: [],
                display: ChartDisplayType.ActionsLineGraph,
                interval: 'week',
                date_from: '-8w',
                properties: [],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'signed_up',
                        math: BaseMathType.TotalCount,
                    },
                ],
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                interval: 'week',
                dateRange: {
                    date_from: '-8w',
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Homepage view to signup conversion` insight', () => {
            const filters: Partial<FunnelsFilterType> = {
                insight: InsightType.FUNNELS,
                date_from: '-1m',
                actions: [],
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                        properties: [
                            {
                                key: '$current_url',
                                type: 'event',
                                value: 'https://hedgebox.net/',
                                operator: 'exact',
                            },
                        ],
                        custom_name: 'Viewed homepage',
                    },
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 1,
                        properties: [
                            {
                                key: '$current_url',
                                type: 'event',
                                value: 'https://hedgebox.net/signup/',
                                operator: 'regex',
                            },
                        ],
                        custom_name: 'Viewed signup page',
                    },
                    {
                        id: 'signed_up',
                        name: 'signed_up',
                        type: 'events',
                        order: 2,
                        custom_name: 'Signed up',
                    },
                ],
                filter_test_accounts: true,
                funnel_viz_type: FunnelVizType.Steps,
                exclusions: [],
            }

            const result = filtersToQueryNode(filters)

            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                dateRange: {
                    date_from: '-1m',
                },
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        properties: [
                            {
                                key: '$current_url',
                                type: PropertyFilterType.Event,
                                value: 'https://hedgebox.net/',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        custom_name: 'Viewed homepage',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        properties: [
                            {
                                key: '$current_url',
                                type: PropertyFilterType.Event,
                                value: 'https://hedgebox.net/signup/',
                                operator: PropertyOperator.Regex,
                            },
                        ],
                        custom_name: 'Viewed signup page',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'signed_up',
                        name: 'signed_up',
                        custom_name: 'Signed up',
                        math: BaseMathType.TotalCount,
                    },
                ],
                filterTestAccounts: true,
                funnelsFilter: {
                    funnel_viz_type: FunnelVizType.Steps,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Activation` insight', () => {
            const filters: Partial<FunnelsFilterType> = {
                insight: InsightType.FUNNELS,
                date_from: '-1m',
                actions: [
                    {
                        id: 1,
                        name: 'Interacted with file',
                        type: 'actions',
                        order: 3,
                    },
                ],
                events: [
                    {
                        id: 'signed_up',
                        name: 'signed_up',
                        type: 'events',
                        order: 2,
                        custom_name: 'Signed up',
                    },
                    {
                        id: 'upgraded_plan',
                        name: 'upgraded_plan',
                        type: 'events',
                        order: 4,
                        custom_name: 'Upgraded plan',
                    },
                ],
                filter_test_accounts: true,
                funnel_viz_type: FunnelVizType.Steps,
                exclusions: [],
            }

            const result = filtersToQueryNode(filters)

            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                dateRange: {
                    date_from: '-1m',
                },
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'signed_up',
                        name: 'signed_up',
                        custom_name: 'Signed up',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.ActionsNode,
                        id: 1,
                        name: 'Interacted with file',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'upgraded_plan',
                        name: 'upgraded_plan',
                        custom_name: 'Upgraded plan',
                        math: BaseMathType.TotalCount,
                    },
                ],
                filterTestAccounts: true,
                funnelsFilter: {
                    funnel_viz_type: FunnelVizType.Steps,
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `Weekly file volume` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'uploaded_file',
                        math: 'sum',
                        name: 'uploaded_file',
                        type: 'events',
                        order: 0,
                        custom_name: 'Uploaded bytes',
                        math_property: 'file_size_b',
                    },
                    {
                        id: 'deleted_file',
                        math: 'sum',
                        name: 'deleted_file',
                        type: 'events',
                        order: 1,
                        custom_name: 'Deleted bytes',
                        math_property: 'file_size_b',
                    },
                ],
                actions: [],
                display: ChartDisplayType.ActionsLineGraph,
                interval: 'week',
                date_from: '-8w',
                new_entity: [],
                properties: [],
                filter_test_accounts: true,
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'uploaded_file',
                        name: 'uploaded_file',
                        custom_name: 'Uploaded bytes',
                        math: PropertyMathType.Sum,
                        math_property: 'file_size_b',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'deleted_file',
                        name: 'deleted_file',
                        custom_name: 'Deleted bytes',
                        math: PropertyMathType.Sum,
                        math_property: 'file_size_b',
                    },
                ],
                interval: 'week',
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                dateRange: {
                    date_from: '-8w',
                },
                filterTestAccounts: true,
            }
            expect(result).toEqual(query)
        })

        it('converts `File interactions` insight', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'uploaded_file',
                        type: 'events',
                        order: 0,
                    },
                    {
                        id: 'deleted_file',
                        type: 'events',
                        order: 2,
                    },
                    {
                        id: 'downloaded_file',
                        type: 'events',
                        order: 1,
                    },
                ],
                actions: [],
                display: ChartDisplayType.ActionsLineGraph,
                interval: 'day',
                date_from: '-30d',
                properties: [],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'uploaded_file',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'downloaded_file',
                        math: BaseMathType.TotalCount,
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'deleted_file',
                        math: BaseMathType.TotalCount,
                    },
                ],
                interval: 'day',
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                dateRange: {
                    date_from: '-30d',
                },
            }
            expect(result).toEqual(query)
        })

        it('converts `User paths starting at homepage` insight', () => {
            const filters: Partial<PathsFilterType> = {
                insight: InsightType.PATHS,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
                start_point: 'https://hedgebox.net/',
                step_limit: 5,
                include_event_types: [PathType.PageView],
                path_groupings: ['/files/*'],
                exclude_events: [],
                date_from: '-30d',
                date_to: null,
                funnel_filter: {},
                local_path_cleaning_filters: [],
                edge_limit: 50,
            }

            const result = filtersToQueryNode(filters)

            const query: PathsQuery = {
                kind: NodeKind.PathsQuery,
                dateRange: {
                    date_from: '-30d',
                    date_to: null,
                },
                pathsFilter: {
                    start_point: 'https://hedgebox.net/',
                    step_limit: 5,
                    include_event_types: [PathType.PageView],
                    path_groupings: ['/files/*'],
                    edge_limit: 50,
                },
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
            }
            expect(result).toEqual(query)
        })

        it("converts `Last month's signups by country` insight", () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                events: [
                    {
                        id: 'signed_up',
                        type: 'events',
                        order: 0,
                    },
                ],
                actions: [],
                display: ChartDisplayType.WorldMap,
                breakdown: '$geoip_country_code',
                date_from: '-1m',
                breakdown_type: 'event',
                properties: [],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'signed_up',
                        math: BaseMathType.TotalCount,
                    },
                ],
                trendsFilter: {
                    display: ChartDisplayType.WorldMap,
                },
                breakdown: {
                    breakdown: '$geoip_country_code',
                    breakdown_type: 'event',
                },
                dateRange: {
                    date_from: '-1m',
                },
            }
            expect(result).toEqual(query)
        })
    })
})
