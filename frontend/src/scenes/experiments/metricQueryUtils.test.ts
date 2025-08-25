import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import type {
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ChartDisplayType,
    ExperimentMetricMathType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import {
    createFilterForSource,
    filterToMetricConfig,
    filterToMetricSource,
    getFilter,
    getMathProperties,
    getQuery,
} from './metricQueryUtils'

describe('getFilter', () => {
    it('returns the correct filter for an event', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.TotalCount,
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
            } as EventsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    event: '$pageview',
                    type: 'events',
                    math: ExperimentMetricMathType.TotalCount,
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
                    kind: NodeKind.EventsNode,
                },
            ],
            actions: [],
            data_warehouse: [],
        })
    })
    it('returns the correct filter for an action', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 8,
                name: 'jan-16-running payment action',
                math: ExperimentMetricMathType.TotalCount,
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
            } as ActionsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [],
            actions: [
                {
                    id: 8,
                    name: 'jan-16-running payment action',
                    type: 'actions',
                    math: ExperimentMetricMathType.TotalCount,
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
                    kind: NodeKind.ActionsNode,
                },
            ],
            data_warehouse: [],
        })
    })
})

describe('filterToMetricSource', () => {
    it('returns EventsNode when events are provided', () => {
        const events = [
            {
                id: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.TotalCount,
                math_property: 'revenue',
                math_hogql: 'sum(revenue)',
                properties: [],
            },
        ]

        const result = filterToMetricSource(undefined, events, undefined)

        expect(result).toEqual({
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
            math_property: 'revenue',
            math_hogql: 'sum(revenue)',
            properties: [],
        })
    })

    it('returns ActionsNode when actions are provided', () => {
        const actions = [
            {
                id: 123,
                name: 'signup_action',
                math: ExperimentMetricMathType.Sum,
                math_property: 'value',
                properties: [],
            },
        ]

        const result = filterToMetricSource(actions, undefined, undefined)

        expect(result).toEqual({
            kind: NodeKind.ActionsNode,
            id: 123,
            name: 'signup_action',
            math: ExperimentMetricMathType.Sum,
            math_property: 'value',
            math_hogql: undefined,
            properties: [],
        })
    })

    it('returns ExperimentDataWarehouseNode when data_warehouse is provided', () => {
        const dataWarehouse = [
            {
                id: 'user_events',
                name: 'User Events',
                timestamp_field: 'created_at',
                events_join_key: 'user_id',
                data_warehouse_join_key: 'customer_id',
                math: ExperimentMetricMathType.Avg,
                math_property: 'session_duration',
                properties: [],
            },
        ]

        const result = filterToMetricSource(undefined, undefined, dataWarehouse)

        expect(result).toEqual({
            kind: NodeKind.ExperimentDataWarehouseNode,
            name: 'User Events',
            table_name: 'user_events',
            timestamp_field: 'created_at',
            events_join_key: 'user_id',
            data_warehouse_join_key: 'customer_id',
            math: ExperimentMetricMathType.Avg,
            math_property: 'session_duration',
            math_hogql: undefined,
            properties: [],
        })
    })

    it('returns null when no sources are provided', () => {
        const result = filterToMetricSource(undefined, undefined, undefined)
        expect(result).toBeNull()
    })

    it('prioritizes events over actions and data_warehouse', () => {
        const events = [{ id: 'event1', name: 'Event 1' }]
        const actions = [{ id: 1, name: 'Action 1' }]
        const dataWarehouse = [{ id: 'table1', name: 'Table 1' }]

        const result = filterToMetricSource(actions, events, dataWarehouse)

        expect(result?.kind).toBe(NodeKind.EventsNode)
        expect(result?.name).toBe('Event 1')
    })

    it('uses default math when not provided', () => {
        const events = [{ id: '$pageview', name: '$pageview' }]

        const result = filterToMetricSource(undefined, events, undefined)

        expect(result?.math).toBe(ExperimentMetricMathType.TotalCount)
    })
})

describe('filterToMetricConfig', () => {
    it('returns FUNNEL metric config when funnel type is provided', () => {
        const events = [
            { id: 'step1', properties: [], order: 0 },
            { id: 'step2', properties: [], order: 1 },
        ]
        const actions = [{ id: 123, name: 'action1', properties: [], order: 2 }]

        const result = filterToMetricConfig(ExperimentMetricType.FUNNEL, actions, events, undefined)

        expect(result).toEqual({
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                { kind: NodeKind.EventsNode, event: 'step1', properties: [] },
                { kind: NodeKind.EventsNode, event: 'step2', properties: [] },
                { kind: NodeKind.ActionsNode, id: 123, name: 'action1', properties: [] },
            ],
        })
    })

    it('returns MEAN metric config when mean type is provided with events', () => {
        const events = [
            { id: 'purchase', name: 'Purchase Event', math: ExperimentMetricMathType.Sum, math_property: 'revenue' },
        ]

        const result = filterToMetricConfig(ExperimentMetricType.MEAN, undefined, events, undefined)

        expect(result).toEqual({
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'purchase',
                name: 'Purchase Event',
                math: ExperimentMetricMathType.Sum,
                math_property: 'revenue',
                math_hogql: undefined,
                properties: undefined,
            },
        })
    })

    it('returns undefined when no valid sources are provided', () => {
        const result = filterToMetricConfig(ExperimentMetricType.MEAN, undefined, undefined, undefined)
        expect(result).toBeUndefined()
    })

    it('returns undefined for unsupported metric types', () => {
        const events = [{ id: 'event1', name: 'Event 1' }]
        const result = filterToMetricConfig('UNSUPPORTED' as ExperimentMetricType, undefined, events, undefined)
        expect(result).toBeUndefined()
    })
})

describe('createFilterForSource', () => {
    it('creates filter for EventsNode source', () => {
        const source: EventsNode = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
            properties: [],
        }

        const result = createFilterForSource(source)

        expect(result.events).toHaveLength(1)
        expect(result.actions).toHaveLength(0)
        expect(result.data_warehouse).toHaveLength(0)
        expect(result.events?.[0]?.id).toBe('$pageview')
        expect(result.events?.[0]?.type).toBe('events')
    })

    it('creates filter for ActionsNode source', () => {
        const source: ActionsNode = {
            kind: NodeKind.ActionsNode,
            id: 123,
            name: 'signup_action',
            math: ExperimentMetricMathType.TotalCount,
        }

        const result = createFilterForSource(source)

        expect(result.events).toHaveLength(0)
        expect(result.actions).toHaveLength(1)
        expect(result.data_warehouse).toHaveLength(0)
        expect(result.actions?.[0]?.id).toBe(123)
        expect(result.actions?.[0]?.type).toBe('actions')
    })

    it('creates filter for ExperimentDataWarehouseNode source', () => {
        const source: ExperimentDataWarehouseNode = {
            kind: NodeKind.ExperimentDataWarehouseNode,
            name: 'revenue_table',
            table_name: 'revenue_table',
            timestamp_field: 'created_at',
            events_join_key: 'user_id',
            data_warehouse_join_key: 'customer_id',
            math: ExperimentMetricMathType.Sum,
        }

        const result = createFilterForSource(source)

        expect(result.events).toHaveLength(0)
        expect(result.actions).toHaveLength(0)
        expect(result.data_warehouse).toHaveLength(1)
        expect(result.data_warehouse?.[0]?.id).toBe('revenue_table')
        expect(result.data_warehouse?.[0]?.type).toBe('data_warehouse')
    })
})

describe('getQuery', () => {
    it('returns the correct query for a funnel metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                {
                    event: 'purchase',
                    kind: NodeKind.EventsNode,
                    name: 'purchase',
                },
            ],
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric)

        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.FunnelsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                funnelsFilter: {
                    layout: FunnelLayout.horizontal,
                },
                filterTestAccounts: false,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        name: 'purchase',
                    },
                ],
            })
        )
    })

    it('returns the correct query for a count metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.TotalCount,
            },
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric)

        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: false,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: ExperimentMetricMathType.TotalCount,
                    },
                ],
            })
        )
    })

    it('returns the correct query for a mean metric with sum math type', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.Sum,
                math_property: 'property_value',
            },
        }

        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
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
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        math: PropertyMathType.Sum,
                        math_property: 'property_value',
                    },
                ],
            })
        )
    })

    it('returns the correct query for a mean metric with unique sessions math type', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.UniqueSessions,
            },
        }
        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
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
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        math: ExperimentMetricMathType.UniqueSessions,
                    },
                ],
            })
        )
    })

    it('returns undefined for unsupported metric types', () => {
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: 'unsupported_type' as ExperimentMetricType,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric as ExperimentMetric)
        expect(query).toBeUndefined()
    })

    it('returns the correct query for a mean metric with properties', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.TotalCount,
                properties: [
                    {
                        key: '$browser',
                        value: ['Chrome'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            },
        }

        const query = getQuery({
            filterTestAccounts: false,
        })(metric)

        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                dateRange: {
                    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    explicitDate: true,
                },
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                },
                filterTestAccounts: false,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: ExperimentMetricMathType.TotalCount,
                        properties: [
                            {
                                key: '$browser',
                                value: ['Chrome'],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
            })
        )
    })

    it('returns the correct query for a mean metric with an action source', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 123,
                name: 'test action',
                math: ExperimentMetricMathType.Sum,
                math_property: 'property_value',
            },
        }

        const query = getQuery({
            filterTestAccounts: true,
        })(metric)
        expect(query).toEqual(
            setLatestVersionsOnQuery({
                kind: NodeKind.TrendsQuery,
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
                series: [
                    {
                        kind: NodeKind.ActionsNode,
                        id: 123,
                        name: 'test action',
                        math: PropertyMathType.Sum,
                        math_property: 'property_value',
                    },
                ],
            })
        )
    })
})

describe('Data Warehouse Support', () => {
    describe('getFilter with data warehouse nodes', () => {
        it('returns the correct filter for a data warehouse mean metric', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'user_events',
                    timestamp_field: 'created_at',
                    events_join_key: 'user_id',
                    data_warehouse_join_key: 'user_id',
                    name: 'user_events',
                    math: ExperimentMetricMathType.TotalCount,
                    properties: [
                        {
                            key: 'event_type',
                            value: ['purchase'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                } as ExperimentDataWarehouseNode,
            }
            const filter = getFilter(metric)
            expect(filter).toEqual({
                events: [],
                actions: [],
                data_warehouse: [
                    {
                        id: 'user_events',
                        name: 'user_events',
                        type: 'data_warehouse',
                        table_name: 'user_events',
                        timestamp_field: 'created_at',
                        events_join_key: 'user_id',
                        data_warehouse_join_key: 'user_id',
                        math: ExperimentMetricMathType.TotalCount,
                        properties: [
                            {
                                key: 'event_type',
                                value: ['purchase'],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                        kind: NodeKind.ExperimentDataWarehouseNode,
                    },
                ],
            })
        })

        it('handles funnel metrics with mixed steps (events and actions only)', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.FUNNEL,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                    } as EventsNode,
                    {
                        kind: NodeKind.ActionsNode,
                        id: 42,
                        name: 'subscription_action',
                    } as ActionsNode,
                ],
            }
            const filter = getFilter(metric)
            expect(filter).toEqual({
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        event: '$pageview',
                        type: 'events',
                        order: 0,
                        kind: NodeKind.EventsNode,
                    },
                ],
                actions: [
                    {
                        id: 42,
                        name: 'subscription_action',
                        type: 'actions',
                        order: 1,
                        kind: NodeKind.ActionsNode,
                    },
                ],
                data_warehouse: [], // Data warehouse nodes are not supported in funnel metrics
            })
        })
    })

    describe('getQuery with data warehouse nodes', () => {
        it('returns the correct query for a data warehouse mean metric', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'revenue_table',
                    timestamp_field: 'transaction_date',
                    events_join_key: 'user_id',
                    data_warehouse_join_key: 'customer_id',
                    name: 'revenue_table',
                    math: ExperimentMetricMathType.Sum,
                    math_property: 'revenue_amount',
                } as ExperimentDataWarehouseNode,
            }

            const query = getQuery({
                filterTestAccounts: true,
            })(metric)

            expect(query).toEqual(
                setLatestVersionsOnQuery({
                    kind: NodeKind.TrendsQuery,
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
                    series: [
                        {
                            kind: NodeKind.DataWarehouseNode,
                            table_name: 'revenue_table',
                            timestamp_field: 'transaction_date',
                            distinct_id_field: 'user_id',
                            id_field: 'customer_id',
                            id: 'revenue_table',
                            name: 'revenue_table',
                            math: PropertyMathType.Sum,
                            math_property: 'revenue_amount',
                        },
                    ],
                })
            )
        })

        it('returns the correct query for funnel metrics with events and actions', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.FUNNEL,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'landing_page_view',
                        name: 'landing_page_view',
                    } as EventsNode,
                    {
                        kind: NodeKind.ActionsNode,
                        id: 123,
                        name: 'signup_action',
                    } as ActionsNode,
                ],
            }

            const query = getQuery({
                filterTestAccounts: false,
            })(metric)

            expect(query?.kind).toBe(NodeKind.FunnelsQuery)
            expect(query?.series).toEqual([
                {
                    kind: NodeKind.EventsNode,
                    event: 'landing_page_view',
                    name: 'landing_page_view',
                },
                {
                    kind: NodeKind.ActionsNode,
                    id: 123,
                    name: 'signup_action',
                },
            ])
        })

        it('returns undefined for data warehouse mean metric with no math property when math type is sum', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'incomplete_table',
                    timestamp_field: 'created_at',
                    events_join_key: 'user_id',
                    data_warehouse_join_key: 'customer_id',
                    name: 'incomplete_table',
                    // No math property specified
                } as ExperimentDataWarehouseNode,
            }

            const query = getQuery({
                filterTestAccounts: false,
            })(metric)

            expect(query).toBeUndefined()
        })
    })

    describe('Edge cases and validation', () => {
        it('handles empty data warehouse properties gracefully', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: '',
                    timestamp_field: '',
                    events_join_key: '',
                    data_warehouse_join_key: '',
                    name: '',
                    math: ExperimentMetricMathType.TotalCount,
                } as ExperimentDataWarehouseNode,
            }
            const filter = getFilter(metric)
            expect(filter.data_warehouse).toHaveLength(1)
            expect(filter.data_warehouse?.[0]?.table_name).toBe('')
        })

        it('preserves custom names and properties for data warehouse nodes in mean metrics', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'analytics_events',
                    timestamp_field: 'event_time',
                    events_join_key: 'user_uuid',
                    data_warehouse_join_key: 'user_external_id',
                    name: 'analytics_events',
                    custom_name: 'Custom Analytics Event',
                    properties: [
                        {
                            key: 'category',
                            value: ['conversion'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: 'value',
                            value: [100],
                            operator: PropertyOperator.GreaterThanOrEqual,
                            type: PropertyFilterType.Event,
                        },
                    ],
                    math: ExperimentMetricMathType.TotalCount,
                    math_property: 'conversion_value',
                    math_hogql: 'sum(conversion_value)',
                } as ExperimentDataWarehouseNode,
            }
            const filter = getFilter(metric)
            expect(filter.data_warehouse?.[0]).toEqual({
                id: 'analytics_events',
                name: 'analytics_events',
                type: 'data_warehouse',
                table_name: 'analytics_events',
                timestamp_field: 'event_time',
                events_join_key: 'user_uuid',
                data_warehouse_join_key: 'user_external_id',
                custom_name: 'Custom Analytics Event',
                properties: [
                    {
                        key: 'category',
                        value: ['conversion'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: 'value',
                        value: [100],
                        operator: PropertyOperator.GreaterThanOrEqual,
                        type: PropertyFilterType.Event,
                    },
                ],
                math: ExperimentMetricMathType.TotalCount,
                math_property: 'conversion_value',
                math_hogql: 'sum(conversion_value)',
                kind: NodeKind.ExperimentDataWarehouseNode,
            })
        })
    })
})

describe('getMathProperties', () => {
    it('returns TotalCount math properties when no math is specified', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.TotalCount,
            math_property: undefined,
        })
    })

    it('returns TotalCount math properties when math is explicitly TotalCount', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.TotalCount,
            math_property: undefined,
        })
    })

    it('returns UniqueSessions math properties without math_property', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            math: ExperimentMetricMathType.UniqueSessions,
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.UniqueSessions,
        })
    })

    it('returns Sum math properties with math_property', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            math: ExperimentMetricMathType.Sum,
            math_property: 'price',
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.Sum,
            math_property: 'price',
        })
    })

    it('returns Avg math properties with math_property', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: 'session_duration',
            math: ExperimentMetricMathType.Avg,
            math_property: 'duration',
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.Avg,
            math_property: 'duration',
        })
    })

    it('returns Min math properties with math_property', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            math: ExperimentMetricMathType.Min,
            math_property: 'price',
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.Min,
            math_property: 'price',
        })
    })

    it('returns Max math properties with math_property', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            math: ExperimentMetricMathType.Max,
            math_property: 'price',
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.Max,
            math_property: 'price',
        })
    })

    it('preserves undefined math_property for property-based math types', () => {
        const source = {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            math: ExperimentMetricMathType.Avg,
            math_property: undefined,
        } as EventsNode

        const result = getMathProperties(source)
        expect(result).toEqual({
            math: ExperimentMetricMathType.Avg,
            math_property: undefined,
        })
    })
})
