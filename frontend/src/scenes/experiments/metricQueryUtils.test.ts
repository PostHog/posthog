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
import { ChartDisplayType, ExperimentMetricMathType, PropertyMathType } from '~/types'

import { getFilter, getQuery } from './metricQueryUtils'

describe('getFilter', () => {
    it('returns the correct filter for an event', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: 'total',
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
                    math: 'total',
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
                math: 'total',
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
                    math: 'total',
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
                    math: 'total',
                    properties: [{ key: 'event_type', value: ['purchase'], operator: 'exact', type: 'event' }],
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
                        math: 'total',
                        properties: [{ key: 'event_type', value: ['purchase'], operator: 'exact', type: 'event' }],
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
                            kind: NodeKind.ExperimentDataWarehouseNode,
                            table_name: 'revenue_table',
                            timestamp_field: 'transaction_date',
                            events_join_key: 'user_id',
                            data_warehouse_join_key: 'customer_id',
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
                    math: 'total',
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
                        { key: 'category', value: ['conversion'], operator: 'exact', type: 'event' },
                        { key: 'value', value: [100], operator: 'gte', type: 'event' },
                    ],
                    math: 'total',
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
                    { key: 'category', value: ['conversion'], operator: 'exact', type: 'event' },
                    { key: 'value', value: [100], operator: 'gte', type: 'event' },
                ],
                math: 'total',
                math_property: 'conversion_value',
                math_hogql: 'sum(conversion_value)',
                kind: NodeKind.ExperimentDataWarehouseNode,
            })
        })
    })
})
