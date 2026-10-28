import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { getDefaultEventLabel, getDefaultEventName } from 'lib/utils/getAppContext'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import type {
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetricStep,
    ExperimentMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'
import {
    ChartDisplayType,
    ExperimentMetricMathType,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import {
    getMathProperties,
    getQuery,
    metricSourcesToSeries,
    seriesToMetricConfig,
    seriesToMetricSource,
} from './metricQueryUtils'

// getQuery builds date_from/date_to from dayjs() at call time, formatted to the minute.
// The expected values below recompute dayjs() independently, so a minute rollover between
// the two reads makes the strings differ and toEqual flakes. Freeze the clock (no
// advanceTimers, so it cannot move) to make both reads resolve to the same instant.
beforeAll(() => {
    jest.useFakeTimers().setSystemTime(new Date('2026-01-15T12:00:00'))
})

afterAll(() => {
    jest.useRealTimers()
})

describe('seriesToMetricSource', () => {
    const pickedTable = {
        table_name: 'stripe_charges',
        name: 'stripe_charges',
        timestamp_field: 'created_at',
        events_join_key: 'distinct_id',
        data_warehouse_join_key: 'customer_id',
        math: ExperimentMetricMathType.Sum,
        math_property: 'amount',
    }

    it.each([NodeKind.ExperimentDataWarehouseNode, NodeKind.DataWarehouseNode] as const)(
        'stores a table picked as %s as an experiment warehouse node, without the id the picker mirrors',
        (kind) => {
            const series = [{ ...pickedTable, kind, id: 'stripe_charges' }] as SeriesNode[]

            expect(seriesToMetricSource(series)).toEqual({
                ...pickedTable,
                kind: NodeKind.ExperimentDataWarehouseNode,
            })
        }
    )

    // Regression: an empty/null `event` must fall back to `name` so the event isn't dropped.
    it.each([
        ['empty string event (numerator path)', ''],
        ['null event (denominator path)', null],
    ])('recovers event from name when the node has %s', (_label, event) => {
        const series: SeriesNode[] = [{ kind: NodeKind.EventsNode, event, name: 'purchase' }]

        expect(seriesToMetricSource(series)).toEqual({
            kind: NodeKind.EventsNode,
            event: 'purchase',
            name: 'purchase',
            math: ExperimentMetricMathType.TotalCount,
        })
    })

    it('keeps the session property math type and fixed properties the backend reads', () => {
        const node: EventsNode = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.Sum,
            math_property: '$pageview_count',
            math_property_type: 'session_properties',
            fixedProperties: [
                {
                    key: '$browser',
                    value: ['Chrome'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        }

        expect(seriesToMetricSource([node])).toEqual(node)
    })

    it.each([
        ['no series', []],
        ['a group', [{ kind: NodeKind.GroupNode, operator: FilterLogicalOperator.Or, nodes: [] }]],
    ])('returns null for %s', (_label, series) => {
        expect(seriesToMetricSource(series as SeriesNode[])).toBeNull()
    })
})

describe('seriesToMetricConfig', () => {
    const funnelSteps: ExperimentFunnelMetricStep[] = [
        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
        { kind: NodeKind.ActionsNode, id: 7, name: 'Signed up' },
        {
            kind: NodeKind.ExperimentDataWarehouseNode,
            table_name: 'stripe_charges',
            name: 'stripe_charges',
            timestamp_field: 'created_at',
            events_join_key: 'distinct_id',
            data_warehouse_join_key: 'customer_id',
        },
    ]
    const [pageviewStep, actionStep, tableStep] = funnelSteps

    beforeEach(() => {
        initKeaTests()
    })

    it.each<[string, (logic: ReturnType<typeof entityFilterLogic.build>) => void, ExperimentFunnelMetricStep[]]>([
        [
            'adding a step',
            (logic) => logic.actions.addSeries(),
            [...funnelSteps, { kind: NodeKind.EventsNode, event: getDefaultEventName(), name: getDefaultEventLabel() }],
        ],
        [
            'picking a table for a step',
            (logic) =>
                logic.actions.updateSeriesEntity(0, {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    key: 'invoices',
                    name: 'invoices',
                    timestamp_field: 'paid_at',
                    data_warehouse_join_key: 'customer_id',
                    events_join_key: 'distinct_id',
                }),
            [
                {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'invoices',
                    name: 'invoices',
                    timestamp_field: 'paid_at',
                    data_warehouse_join_key: 'customer_id',
                    events_join_key: 'distinct_id',
                },
                actionStep,
                tableStep,
            ],
        ],
        [
            'picking an event for a table step',
            (logic) => logic.actions.updateSeriesEntity(2, { kind: NodeKind.EventsNode, key: 'paid', name: 'paid' }),
            [pageviewStep, actionStep, { kind: NodeKind.EventsNode, event: 'paid', name: 'paid' }],
        ],
        [
            'renaming an action step',
            (logic) => {
                logic.actions.selectSeries(1, logic.values.localSeries[1].node, logic.values.localSeries[1].uuid)
                logic.actions.renameSeries('Signup')
            },
            [pageviewStep, { ...actionStep, custom_name: 'Signup' }, tableStep],
        ],
        ['removing a step', (logic) => logic.actions.removeSeries(1), [pageviewStep, tableStep]],
        [
            'reordering the steps',
            (logic) => logic.actions.setLocalSeries([...logic.values.localSeries].reverse()),
            [tableStep, actionStep, pageviewStep],
        ],
    ])('stores the funnel steps the picker emits after %s', (_label, edit, expectedSteps) => {
        const onChange = jest.fn()
        const logic = entityFilterLogic({
            series: metricSourcesToSeries(funnelSteps),
            onChange,
            typeKey: 'experiment-metric',
            dataWarehouseNodeKind: NodeKind.ExperimentDataWarehouseNode,
            dataWarehousePopoverFields: [
                { key: 'timestamp_field', label: 'Timestamp Field' },
                { key: 'data_warehouse_join_key', label: 'Data Warehouse Join Key' },
                { key: 'events_join_key', label: 'Events Join Key' },
            ],
        })
        logic.mount()

        edit(logic)

        expect(seriesToMetricConfig(ExperimentMetricType.FUNNEL, onChange.mock.lastCall[0])).toEqual({
            metric_type: ExperimentMetricType.FUNNEL,
            series: expectedSteps,
        })
    })

    it('drops math and the optional flag from funnel steps', () => {
        const series: SeriesNode[] = [
            { kind: NodeKind.EventsNode, event: '$pageview', math: ExperimentMetricMathType.TotalCount },
            {
                kind: NodeKind.EventsNode,
                event: 'purchase',
                math: ExperimentMetricMathType.Sum,
                math_property: 'amount',
                optionalInFunnel: true,
            },
        ]

        expect(seriesToMetricConfig(ExperimentMetricType.FUNNEL, series)).toEqual({
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.EventsNode, event: 'purchase' },
            ],
        })
    })

    it('keeps a renamed step of every kind and drops an empty rename', () => {
        const series = [
            { kind: NodeKind.EventsNode, event: 'step1', custom_name: 'Signed up' },
            { kind: NodeKind.EventsNode, event: 'step2', custom_name: '' },
            { kind: NodeKind.ActionsNode, id: 123, name: 'action1', custom_name: 'Activated' },
            {
                kind: NodeKind.ExperimentDataWarehouseNode,
                id: 'stripe_charges',
                table_name: 'stripe_charges',
                name: 'Stripe charges',
                custom_name: 'Paid',
                timestamp_field: 'created_at',
                events_join_key: 'distinct_id',
                data_warehouse_join_key: 'customer_id',
            },
        ] as SeriesNode[]

        expect(seriesToMetricConfig(ExperimentMetricType.FUNNEL, series)).toEqual({
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                { kind: NodeKind.EventsNode, event: 'step1', custom_name: 'Signed up' },
                { kind: NodeKind.EventsNode, event: 'step2' },
                { kind: NodeKind.ActionsNode, id: 123, name: 'action1', custom_name: 'Activated' },
                {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'stripe_charges',
                    name: 'Stripe charges',
                    custom_name: 'Paid',
                    timestamp_field: 'created_at',
                    events_join_key: 'distinct_id',
                    data_warehouse_join_key: 'customer_id',
                },
            ],
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

        it('returns the correct query for funnel metrics with events, actions and data warehouse steps', () => {
            const metric: ExperimentMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.FUNNEL,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'landing_page_view',
                        name: 'landing_page_view',
                        properties: [
                            {
                                key: 'plan',
                                value: ['paid'],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    } as EventsNode,
                    {
                        kind: NodeKind.ActionsNode,
                        id: 123,
                        name: 'signup_action',
                    } as ActionsNode,
                    {
                        kind: NodeKind.ExperimentDataWarehouseNode,
                        table_name: 'stripe_charges',
                        name: 'Stripe charges',
                        timestamp_field: 'created_at',
                        events_join_key: 'distinct_id',
                        data_warehouse_join_key: 'customer_id',
                    } as ExperimentDataWarehouseNode,
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
                    properties: [
                        {
                            key: 'plan',
                            value: ['paid'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
                {
                    kind: NodeKind.ActionsNode,
                    id: 123,
                    name: 'signup_action',
                },
                {
                    kind: NodeKind.FunnelsDataWarehouseNode,
                    id: 'stripe_charges',
                    name: 'Stripe charges',
                    table_name: 'stripe_charges',
                    timestamp_field: 'created_at',
                    id_field: 'customer_id',
                    aggregation_target_field: 'distinct_id',
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
