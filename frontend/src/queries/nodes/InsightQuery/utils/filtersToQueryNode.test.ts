import { FunnelLayout, ShownAsValue } from 'lib/constants'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    FunnelsQuery,
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    ActionFilter,
    BaseMathType,
    BreakdownAttributionType,
    ChartDisplayType,
    FilterLogicalOperator,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelPathType,
    FunnelStepReference,
    FunnelVizType,
    FunnelsFilterType,
    GroupMathType,
    InsightType,
    LifecycleFilterType,
    PathType,
    PathsFilterType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    RetentionFilterType,
    RetentionPeriod,
    StepOrderValue,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

import {
    actionsAndEventsToSeries,
    filtersToQueryNode,
    hiddenLegendKeysToBreakdowns,
    hiddenLegendKeysToIndexes,
} from './filtersToQueryNode'

describe('actionsAndEventsToSeries', () => {
    it('sorts series by order', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', order: 1, name: 'item2', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item3' },
        ]

        const result = actionsAndEventsToSeries({ actions, events }, false, MathAvailability.None)

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

        const result = actionsAndEventsToSeries({ actions, events }, false, MathAvailability.None)

        expect(result[0].name).toEqual('itemWithOrder')
        expect(result[1].name).toEqual('item1')
        expect(result[2].name).toEqual('item2')
    })

    it('assumes typeless series is an event series', () => {
        const events: ActionFilter[] = [{ id: '$pageview', order: 0, name: 'item1' } as any]

        const result = actionsAndEventsToSeries({ events }, false, MathAvailability.None)

        expect(result[0].kind).toEqual(NodeKind.EventsNode)
    })

    it('converts funnels math types', () => {
        const actions: ActionFilter[] = [
            { type: 'actions', id: '1', order: 0, name: 'item1', math: 'total' },
            { type: 'actions', id: '1', order: 1, name: 'item2', math: 'first_time_for_user' },
        ]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 2, name: 'item3', math: 'total' },
            { id: '$autocapture', type: 'events', order: 3, name: 'item4', math: 'first_time_for_user' },
        ]

        const result = actionsAndEventsToSeries({ events, actions }, false, MathAvailability.FunnelsOnly)

        expect(result).toEqual([
            {
                kind: NodeKind.ActionsNode,
                id: '1',
                name: 'item1',
            },
            {
                kind: NodeKind.ActionsNode,
                id: '1',
                name: 'item2',
                math: BaseMathType.FirstTimeForUser,
            },
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: 'item3',
            },
            {
                kind: NodeKind.EventsNode,
                event: '$autocapture',
                name: 'item4',
                math: BaseMathType.FirstTimeForUser,
            },
        ])
    })
})

describe('hiddenLegendKeysToIndexes', () => {
    it('converts legend keys', () => {
        const keys: Record<string, boolean | undefined> = {
            1: true,
            2: false,
            3: undefined,
        }

        const result = hiddenLegendKeysToIndexes(keys)

        expect(result).toEqual([1])
    })

    it('handles undefined legend keys', () => {
        const keys = undefined

        const result = hiddenLegendKeysToIndexes(keys)

        expect(result).toEqual(undefined)
    })

    it('ignores invalid keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            'events/$pageview/0/Baseline': true,
            1: true,
        }

        const result = hiddenLegendKeysToIndexes(keys)

        expect(result).toEqual([1])
    })
})

describe('hiddenLegendKeysToBreakdowns', () => {
    it('converts legend keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Chrome: true,
            'Chrome iOS': true,
            Firefox: false,
            Safari: undefined,
        }

        const result = hiddenLegendKeysToBreakdowns(keys)

        expect(result).toEqual(['Chrome', 'Chrome iOS'])
    })

    it('handles undefined legend keys', () => {
        const keys = undefined

        const result = hiddenLegendKeysToBreakdowns(keys)

        expect(result).toEqual(undefined)
    })

    it('converts legacy format', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            'events/$pageview/0/Baseline': true,
            1: true,
        }

        const result = hiddenLegendKeysToBreakdowns(keys)

        expect(result).toEqual(['Opera', 'Baseline'])
    })

    it('ignores digit-only keys', () => {
        const keys: Record<string, boolean | undefined> = {
            Opera: true,
            1: true,
        }

        const result = hiddenLegendKeysToBreakdowns(keys)

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
                retentionFilter: {
                    meanRetentionCalculation: 'simple',
                },
            } as InsightQueryNode
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
                retentionFilter: {
                    meanRetentionCalculation: 'simple',
                },
            } as InsightQueryNode
            expect(result).toEqual(query)
        })

        it('converts broken grouped properties', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.RETENTION,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: 'email',
                            type: PropertyFilterType.Person,
                            value: 'is_set',
                            operator: PropertyOperator.IsSet,
                        },
                    ] as any,
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
                retentionFilter: {
                    meanRetentionCalculation: 'simple',
                },
            } as InsightQueryNode
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
                retentionFilter: {
                    meanRetentionCalculation: 'simple',
                },
            } as InsightQueryNode
            expect(result).toEqual(query)
        })

        it('converts date range with explicit date setting', () => {
            const filters: Partial<FilterType> = {
                insight: InsightType.RETENTION,
                date_to: '2021-12-08',
                date_from: '2021-12-08',
                explicit_date: 'y',
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.RetentionQuery,
                dateRange: {
                    date_to: '2021-12-08',
                    date_from: '2021-12-08',
                    explicitDate: true,
                },
                retentionFilter: {
                    meanRetentionCalculation: 'simple',
                },
            } as InsightQueryNode
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

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                series: [],
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
                compare_to: '-4d',
                aggregation_axis_format: 'numeric',
                aggregation_axis_prefix: '£',
                aggregation_axis_postfix: '%',
                decimal_places: 8,
                breakdown_histogram_bin_count: 1,
                formula: 'A+B',
                shown_as: ShownAsValue.VOLUME,
                display: ChartDisplayType.ActionsAreaGraph,
                show_percent_stack_view: true,
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                trendsFilter: {
                    smoothingIntervals: 1,
                    showLegend: true,
                    hiddenLegendIndexes: [0, 10],
                    aggregationAxisFormat: 'numeric',
                    aggregationAxisPrefix: '£',
                    aggregationAxisPostfix: '%',
                    decimalPlaces: 8,
                    formula: 'A+B',
                    display: ChartDisplayType.ActionsAreaGraph,
                    showPercentStackView: true,
                },
                breakdownFilter: {
                    breakdown_histogram_bin_count: 1,
                },
                compareFilter: {
                    compare: true,
                    compare_to: '-4d',
                },
                series: [],
            }
            expect(result).toEqual(query)
        })

        it('converts multiple breakdowns', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                breakdowns: [
                    {
                        type: 'event',
                        property: '$pathname',
                        normalize_url: true,
                    },
                    {
                        type: 'group',
                        property: '$num',
                        group_type_index: 0,
                        histogram_bin_count: 10,
                    },
                ],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                breakdownFilter: {
                    breakdowns: [
                        {
                            type: 'event',
                            property: '$pathname',
                            normalize_url: true,
                        },
                        {
                            type: 'group',
                            property: '$num',
                            group_type_index: 0,
                            histogram_bin_count: 10,
                        },
                    ],
                },
                series: [],
            }
            expect(result).toEqual(query)
        })

        it('converts legacy funnel breakdowns', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                breakdowns: [
                    {
                        type: 'event',
                        property: '$current_url',
                    },
                    {
                        property: '$pathname',
                    } as any,
                ],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                breakdownFilter: {
                    breakdowns: [
                        {
                            type: 'event',
                            property: '$current_url',
                        },
                        {
                            type: 'event',
                            property: '$pathname',
                        },
                    ],
                },
                series: [],
            }
            expect(result).toEqual(query)
        })

        it('does not add breakdown_type for multiple breakdowns', () => {
            const filters: Partial<TrendsFilterType> = {
                insight: InsightType.TRENDS,
                breakdowns: [
                    {
                        type: 'person',
                        property: '$browser',
                    },
                ],
            }

            const result = filtersToQueryNode(filters)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                breakdownFilter: {
                    breakdowns: [
                        {
                            type: 'person',
                            property: '$browser',
                        },
                    ],
                    breakdown_type: undefined,
                },
                series: [],
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
                    hiddenLegendBreakdowns: ['Chrome', 'Safari'],
                },
                series: [],
            }
            expect(result).toEqual(query)
        })

        it('converts math type', () => {
            const filters: Partial<FunnelsFilterType> = {
                events: [{ id: '$pageview', type: 'events', order: 0, math: BaseMathType.FirstTimeForUser }],
                insight: InsightType.FUNNELS,
            }

            const result = filtersToQueryNode(filters)

            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        math: BaseMathType.FirstTimeForUser,
                    },
                ],
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
                returning_entity: { id: '1' },
                target_entity: { id: '1' },
                period: RetentionPeriod.Day,
                show_mean: true,
            }

            const result = filtersToQueryNode(filters)

            const query: RetentionQuery = {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {
                    retentionType: 'retention_first_time',
                    retentionReference: 'total',
                    totalIntervals: 2,
                    returningEntity: { id: '1' },
                    targetEntity: { id: '1' },
                    period: RetentionPeriod.Day,
                    meanRetentionCalculation: 'simple',
                },
            }
            expect(result).toEqual(query)
        })
    })

    describe('paths filter', () => {
        it('converts all properties', () => {
            const filters: Partial<PathsFilterType> = {
                insight: InsightType.PATHS,
                include_event_types: [PathType.Screen, PathType.PageView],
                start_point: 'a',
                end_point: 'b',
                path_groupings: ['c', 'd'],
                funnel_paths: FunnelPathType.between,
                funnel_filter: {
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
                    exclusions: [],
                    funnel_step: 1,
                    funnel_viz_type: 'steps',
                    insight: 'FUNNELS',
                },
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
            expect(result).toEqual(query)
        })
    })

    describe('stickiness filter', () => {
        it('converts all properties', () => {
            const filters: Partial<StickinessFilterType> = {
                insight: InsightType.STICKINESS,
                compare: true,
                compare_to: '-4d',
                show_legend: true,
                hidden_legend_keys: { 0: true, 10: true },
                shown_as: ShownAsValue.STICKINESS,
                display: ChartDisplayType.ActionsLineGraph,
            }

            const result = filtersToQueryNode(filters)

            const query: StickinessQuery = {
                kind: NodeKind.StickinessQuery,
                stickinessFilter: {
                    showLegend: true,
                    hiddenLegendIndexes: [0, 10],
                    display: ChartDisplayType.ActionsLineGraph,
                },
                compareFilter: {
                    compare: true,
                    compare_to: '-4d',
                },
                series: [],
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

            const query: LifecycleQuery = {
                kind: NodeKind.LifecycleQuery,
                lifecycleFilter: {
                    toggledLifecycles: ['new', 'dormant'],
                },
                series: [],
            }
            expect(result).toEqual(query)
        })
    })

    describe('malformed properties', () => {
        it('converts properties', () => {
            const properties: any = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key: 'event',
                                type: PropertyFilterType.Event,
                                value: 'value',
                            },
                        ],
                    },
                ],
            }

            const filters: Partial<FilterType> = {
                insight: InsightType.TRENDS,
                properties,
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.TrendsQuery,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'event',
                                    type: PropertyFilterType.Event,
                                    value: 'value',
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                },
                series: [],
            }
            expect(result).toEqual(query)
        })

        it('converts properties with the correct cohort structure', () => {
            const properties: any = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key: 'id',
                                type: PropertyFilterType.Cohort,
                                value: 6,
                                operator: 'in',
                            },
                        ],
                    },
                ],
            }

            const filters: Partial<FilterType> = {
                insight: InsightType.TRENDS,
                properties,
            }

            const result = filtersToQueryNode(filters)

            const query: InsightQueryNode = {
                kind: NodeKind.TrendsQuery,
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: 'id',
                                    type: PropertyFilterType.Cohort,
                                    operator: PropertyOperator.In,
                                    value: 6,
                                },
                            ],
                        },
                    ],
                },
                series: [],
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
                    meanRetentionCalculation: 'simple',
                    period: RetentionPeriod.Week,
                    targetEntity: {
                        id: 'signed_up',
                        name: 'signed_up',
                        type: 'events',
                        order: 0,
                    },
                    retentionType: 'retention_first_time',
                    totalIntervals: 9,
                    returningEntity: {
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
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
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
                    },
                ],
                interval: 'day',
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
                    display: ChartDisplayType.BoldNumber,
                },
                compareFilter: {
                    compare: true,
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
                breakdown: '$current_url',
                breakdown_type: 'event',
                breakdown_normalize_url: true,
                breakdown_hide_other_aggregation: true,
                breakdown_limit: 1,
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
                breakdownFilter: {
                    breakdown: '$current_url',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_hide_other_aggregation: true,
                    breakdown_limit: 1,
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
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'signed_up',
                        name: 'signed_up',
                        custom_name: 'Signed up',
                    },
                ],
                filterTestAccounts: true,
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
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
                    },
                    {
                        kind: NodeKind.ActionsNode,
                        id: 1,
                        name: 'Interacted with file',
                    },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'upgraded_plan',
                        name: 'upgraded_plan',
                        custom_name: 'Upgraded plan',
                    },
                ],
                filterTestAccounts: true,
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
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
                    startPoint: 'https://hedgebox.net/',
                    stepLimit: 5,
                    includeEventTypes: [PathType.PageView],
                    pathGroupings: ['/files/*'],
                    edgeLimit: 50,
                },
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
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
                breakdownFilter: {
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
