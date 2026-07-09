import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelInvalidExclusionError, funnelResult } from 'scenes/funnels/__mocks__/funnelDataLogicMocks'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { funnelsQueryDefault, trendsQueryDefault } from '~/queries/nodes/InsightQuery/defaults'
import { FunnelsQuery, LifecycleQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    BaseMathType,
    ChartDisplayType,
    FunnelVizType,
    InsightModel,
    InsightShortId,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { insightDataLogic } from './insightDataLogic'

const Insight123 = '123' as InsightShortId

describe('insightVizDataLogic', () => {
    let builtInsightVizDataLogic: ReturnType<typeof insightVizDataLogic.build>
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let builtFeatureFlagLogic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()

        builtFeatureFlagLogic = featureFlagLogic()
        builtFeatureFlagLogic.mount()

        const props = { dashboardItemId: Insight123 }

        builtInsightVizDataLogic = insightVizDataLogic(props)
        builtInsightDataLogic = insightDataLogic(props)

        builtInsightDataLogic.mount()
        builtInsightVizDataLogic.mount()
    })

    describe('updateQuerySource', () => {
        it('updates the query source', () => {
            // with default query
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({ filterTestAccounts: true })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        filterTestAccounts: true,
                        version: 2,
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.querySource).toMatchObject({ filterTestAccounts: true })

            // merges with existing changes
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({ samplingFactor: 0.1 })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        filterTestAccounts: true,
                        samplingFactor: 0.1,
                        version: 2,
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.querySource).toEqual({
                ...trendsQueryDefault,
                filterTestAccounts: true,
                samplingFactor: 0.1,
                version: 2,
            })
        })

        it('handles funnel step range side effects', () => {
            const querySource = {
                ...funnelsQueryDefault,
                series: [funnelsQueryDefault.series[0], funnelsQueryDefault.series[0], funnelsQueryDefault.series[0]],
                funnelsFilter: {
                    funnelVizType: 'trends',
                    funnelFromStep: 0,
                    funnelToStep: 2,
                },
            } as FunnelsQuery
            builtInsightVizDataLogic.actions.updateQuerySource(querySource)

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    ...querySource,
                    series: querySource.series.slice(0, 2),
                } as FunnelsQuery)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...querySource,
                        series: querySource.series.slice(0, 2),
                        funnelsFilter: {
                            funnelVizType: 'trends',
                            funnelFromStep: 0,
                            funnelToStep: 1,
                        },
                        trendsFilter: {}, // we currently don't remove insight filters of previous query kinds
                        version: 2,
                    },
                },
            })
        })

        it('clamps exclusion step ranges when a funnel step is removed', () => {
            const querySource = {
                ...funnelsQueryDefault,
                series: [funnelsQueryDefault.series[0], funnelsQueryDefault.series[0], funnelsQueryDefault.series[0]],
                funnelsFilter: {
                    funnelVizType: 'steps',
                    exclusions: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$autocapture',
                            event: '$autocapture',
                            funnelFromStep: 0,
                            funnelToStep: 2,
                        },
                    ],
                },
            } as FunnelsQuery
            builtInsightVizDataLogic.actions.updateQuerySource(querySource)

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    ...querySource,
                    series: querySource.series.slice(0, 2),
                } as FunnelsQuery)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...querySource,
                        series: querySource.series.slice(0, 2),
                        funnelsFilter: {
                            funnelVizType: 'steps',
                            exclusions: [
                                {
                                    kind: NodeKind.EventsNode,
                                    name: '$autocapture',
                                    event: '$autocapture',
                                    funnelFromStep: 0,
                                    funnelToStep: 1,
                                },
                            ],
                        },
                        trendsFilter: {},
                        version: 2,
                    },
                },
            })
        })

        it('clears a custom lifecycle aggregation target when switching away from a data warehouse series', () => {
            const lifecycleQuery: LifecycleQuery = {
                kind: NodeKind.LifecycleQuery,
                customAggregationTarget: true,
                series: [
                    {
                        kind: NodeKind.LifecycleDataWarehouseNode,
                        id: 'warehouse_orders',
                        table_name: 'warehouse_orders',
                        name: 'Orders',
                        timestamp_field: 'created_at',
                        aggregation_target_field: 'order_id',
                        created_at_field: 'created_at',
                    },
                ],
            }

            builtInsightVizDataLogic.actions.updateQuerySource(lifecycleQuery)

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    kind: NodeKind.LifecycleQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                } as LifecycleQuery)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.LifecycleQuery,
                        customAggregationTarget: undefined,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                name: '$pageview',
                                event: '$pageview',
                            },
                        ],
                        trendsFilter: {},
                        version: 2,
                    },
                },
            })
        })

        it('clears unsupported lifecycle globals when switching to a data warehouse series', () => {
            const lifecycleQuery: LifecycleQuery = {
                kind: NodeKind.LifecycleQuery,
                filterTestAccounts: true,
                samplingFactor: 0.1,
                properties: [
                    {
                        key: '$browser',
                        value: 'Chrome',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                    },
                ],
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                    },
                ],
            }

            builtInsightVizDataLogic.actions.updateQuerySource(lifecycleQuery)

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    kind: NodeKind.LifecycleQuery,
                    series: [
                        {
                            kind: NodeKind.LifecycleDataWarehouseNode,
                            id: 'warehouse_orders',
                            table_name: 'warehouse_orders',
                            name: 'Orders',
                            timestamp_field: 'created_at',
                            aggregation_target_field: 'order_id',
                            created_at_field: 'created_at',
                        },
                    ],
                } as LifecycleQuery)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.LifecycleQuery,
                        properties: undefined,
                        filterTestAccounts: false,
                        samplingFactor: undefined,
                        series: [
                            {
                                kind: NodeKind.LifecycleDataWarehouseNode,
                                id: 'warehouse_orders',
                                table_name: 'warehouse_orders',
                                name: 'Orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'order_id',
                                created_at_field: 'created_at',
                            },
                        ],
                        trendsFilter: {},
                        version: 2,
                    },
                },
            })
        })

        it('disables filterTestAccounts and properties when adding a data warehouse series to trends', () => {
            builtInsightVizDataLogic.actions.updateQuerySource({
                filterTestAccounts: true,
                properties: [
                    {
                        type: 'event',
                        key: 'browser',
                        value: 'Chrome',
                        operator: 'exact',
                    },
                ],
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                    },
                ],
            } as TrendsQuery)

            expect(builtInsightVizDataLogic.values.querySource).toMatchObject({
                filterTestAccounts: true,
                properties: [expect.objectContaining({ key: 'browser' })],
            })

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.DataWarehouseNode,
                            id: 'warehouse_orders',
                            table_name: 'warehouse_orders',
                            name: 'Orders',
                            timestamp_field: 'created_at',
                            id_field: 'order_id',
                            distinct_id_field: 'customer_id',
                        },
                    ],
                } as TrendsQuery)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: expect.objectContaining({
                        kind: NodeKind.TrendsQuery,
                        filterTestAccounts: false,
                        properties: undefined,
                        series: [
                            expect.objectContaining({
                                kind: NodeKind.DataWarehouseNode,
                                table_name: 'warehouse_orders',
                            }),
                        ],
                    }),
                },
            })
        })
    })

    describe('updateDateRange', () => {
        it('updates the date range', async () => {
            // when dateRange is empty
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_from: '-7d',
                    date_to: null,
                    explicitDate: false,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            interval: 'day', // side effect
                            dateRange: {
                                date_from: '-7d',
                                date_to: null,
                                explicitDate: false,
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: null,
                explicitDate: false,
            })

            // merges with existing dateRange
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_to: '-3d',
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            interval: 'day', // side effect
                            dateRange: {
                                date_from: '-7d',
                                date_to: '-3d',
                                explicitDate: false,
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: '-3d',
                explicitDate: false,
            })
        })

        it('auto-selects quarter interval for >36-month range when flag is on', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]: true,
            })

            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_from: '2020-01-01',
                    date_to: '2024-01-01',
                    explicitDate: true,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: expect.objectContaining({
                            interval: 'quarter',
                        }),
                    },
                })

            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]: false,
            })
        })

        it('auto-selects month interval for >36-month range when flag is off', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]: false,
            })

            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_from: '2020-01-01',
                    date_to: '2024-01-01',
                    explicitDate: true,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: expect.objectContaining({
                            interval: 'month',
                        }),
                    },
                })
        })

        it.each([
            ['2024-06-10 08:00:00', '2024-06-10 14:00:00', 'minute'],
            // A bare same-day pair means "that whole day" and must stay hourly, not 1440 minute buckets
            ['2024-06-10', '2024-06-10', 'hour'],
            // A time-carrying range over 12 hours must not go sub-hour
            ['2024-06-10 08:00:00', '2024-06-11 20:00:00', 'hour'],
            ['2024-06-01', '2024-07-15', 'day'],
        ])('auto-adjusts interval for absolute range %s..%s to %s', async (dateFrom, dateTo, expectedInterval) => {
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({ date_from: dateFrom, date_to: dateTo }, true)
            }).toFinishAllListeners()

            expect((builtInsightVizDataLogic.values.querySource as TrendsQuery).interval).toBe(expectedInterval)
        })
    })

    describe('zoomDateRange', () => {
        it.each([
            ['2024-06-10', '2024-06-12', false],
            ['2024-06-10 08:00:00', '2024-06-10 14:00:00', true],
        ])('zooms %s..%s with explicitDate=%s', async (dateFrom, dateTo, explicitDate) => {
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.zoomDateRange(dateFrom, dateTo)
            }).toFinishAllListeners()

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: dateFrom,
                date_to: dateTo,
                explicitDate,
            })
        })
    })

    describe('updateBreakdownFilter', () => {
        it('updates the breakdown', async () => {
            // when breakdown is empty
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateBreakdownFilter({
                    breakdown_type: 'event',
                    breakdown: '$current_url',
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            breakdownFilter: {
                                breakdown_type: 'event',
                                breakdown: '$current_url',
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.breakdownFilter).toEqual({
                breakdown_type: 'event',
                breakdown: '$current_url',
            })

            // merges with existing breakdown
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateBreakdownFilter({
                    breakdown: '$browser',
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            breakdownFilter: {
                                breakdown_type: 'event',
                                breakdown: '$browser',
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.breakdownFilter).toEqual({
                breakdown_type: 'event',
                breakdown: '$browser',
            })
        })
    })

    describe('updateInsightFilter', () => {
        it('updates the insight filter', async () => {
            // when insight filter is empty
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({ display: ChartDisplayType.ActionsAreaGraph })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            trendsFilter: {
                                display: 'ActionsAreaGraph',
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.insightFilter).toEqual({ display: 'ActionsAreaGraph' })

            // merges with existing insight filter
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({
                    showValuesOnSeries: true,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQueryDefault,
                            trendsFilter: {
                                display: 'ActionsAreaGraph',
                                showValuesOnSeries: true,
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.insightFilter).toEqual({
                display: 'ActionsAreaGraph',
                showValuesOnSeries: true,
            })
        })

        it('updates the insight filter for other insight query kinds', async () => {
            builtInsightVizDataLogic.actions.updateQuerySource(funnelsQueryDefault)

            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({
                    layout: FunnelLayout.horizontal,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...funnelsQueryDefault,
                            funnelsFilter: {
                                ...funnelsQueryDefault.funnelsFilter,
                                layout: FunnelLayout.horizontal,
                            },
                            trendsFilter: {}, // we currently don't remove insight filters of previous query kinds
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.insightFilter).toMatchObject({
                ...funnelsQueryDefault.funnelsFilter,
                layout: FunnelLayout.horizontal,
            })
        })

        it('clears the breakdown when switching to the Metric display', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateBreakdownFilter({
                    breakdown_type: 'event',
                    breakdown: '$browser',
                })
            }).toFinishAllListeners()
            expect((builtInsightVizDataLogic.values.querySource as TrendsQuery).breakdownFilter).toEqual({
                breakdown_type: 'event',
                breakdown: '$browser',
            })

            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({ display: ChartDisplayType.Metric })
            }).toFinishAllListeners()

            expect(builtInsightVizDataLogic.values.querySource).toMatchObject({
                trendsFilter: { display: ChartDisplayType.Metric },
            })
            expect((builtInsightVizDataLogic.values.querySource as TrendsQuery).breakdownFilter).toBeUndefined()
        })
    })

    describe('activeUsersMath', () => {
        it('returns null without active users math', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ activeUsersMath: null })
        })

        it('returns weekly active users math type', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.WeeklyActiveUsers,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ activeUsersMath: BaseMathType.WeeklyActiveUsers })
        })

        it('returns monthly active users math type', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.TotalCount,
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.MonthlyActiveUsers,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ activeUsersMath: BaseMathType.MonthlyActiveUsers })
        })
    })

    describe('enabledIntervals', () => {
        it('returns all intervals', () => {
            expectLogic(builtInsightVizDataLogic).toMatchValues({
                enabledIntervals: {
                    day: { label: 'day', newDateFrom: undefined },
                    minute: { label: 'minute', newDateFrom: 'hStart' },
                    hour: { label: 'hour', newDateFrom: 'dStart' },
                    month: { label: 'month', newDateFrom: '-90d' },
                    week: { label: 'week', newDateFrom: '-30d' },
                    quarter: { label: 'quarter', newDateFrom: '-3y', hidden: true },
                    year: { label: 'year', newDateFrom: '-5y', hidden: true },
                },
            })
        })

        it('unhides quarter and year when the flag is enabled', () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]: true,
            })

            expect(builtInsightVizDataLogic.values.enabledIntervals.quarter).toEqual({
                label: 'quarter',
                newDateFrom: '-3y',
                hidden: false,
            })
            expect(builtInsightVizDataLogic.values.enabledIntervals.year).toEqual({
                label: 'year',
                newDateFrom: '-5y',
                hidden: false,
            })

            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]: false,
            })
        })

        it('adds a disabled reason with active users math', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: 'EventsNode',
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.WeeklyActiveUsers,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({
                enabledIntervals: {
                    day: { label: 'day', newDateFrom: undefined },
                    minute: {
                        label: 'minute',
                        newDateFrom: 'hStart',
                    },
                    hour: {
                        label: 'hour',
                        newDateFrom: 'dStart',
                        disabledReason:
                            'Grouping by hour is not supported on insights with weekly or monthly active users series.',
                    },
                    month: {
                        label: 'month',
                        newDateFrom: '-90d',
                        disabledReason:
                            'Grouping by month is not supported on insights with weekly active users series.',
                    },
                    week: { label: 'week', newDateFrom: '-30d' },
                    quarter: {
                        label: 'quarter',
                        newDateFrom: '-3y',
                        hidden: true,
                        disabledReason:
                            'Grouping by quarter is not supported on insights with weekly active users series.',
                    },
                    year: {
                        label: 'year',
                        newDateFrom: '-5y',
                        hidden: true,
                        disabledReason:
                            'Grouping by year is not supported on insights with weekly active users series.',
                    },
                },
            })
        })

        it('snaps interval to week when switching series to WAU on a quarter-grouped query', () => {
            builtInsightVizDataLogic.actions.updateQuerySource({
                interval: 'quarter',
            } as Partial<TrendsQuery>)

            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                            math: BaseMathType.WeeklyActiveUsers,
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({
                querySource: expect.objectContaining({ interval: 'week' }),
            })
        })

        it('clears smoothing when switching between intervals', async () => {
            const trendsQuery = { ...trendsQueryDefault, interval: 'minute' }
            trendsQuery.trendsFilter = { ...trendsQuery.trendsFilter, smoothingIntervals: 2 }
            builtInsightVizDataLogic.actions.updateQuerySource(trendsQuery)

            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    kind: NodeKind.TrendsQuery,
                    interval: 'hour',
                } as TrendsQuery)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...trendsQuery,
                            interval: 'hour',
                            dateRange: {
                                date_from: '-1h',
                                date_to: undefined,
                            },
                            trendsFilter: { smoothingIntervals: undefined },
                            version: 2,
                        },
                    },
                })
        })
    })

    describe('validationError', () => {
        it('for standard funnel', async () => {
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResult.result,
            }

            await expectLogic(builtInsightVizDataLogic, () => {
                builtInsightDataLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                validationError: null,
            })
        })

        it('for invalid exclusion', async () => {
            await expectLogic(builtInsightVizDataLogic, () => {
                builtInsightDataLogic.actions.loadDataFailure('', { status: 400, ...funnelInvalidExclusionError })
            }).toMatchValues({
                validationError: "Exclusion steps cannot contain an event that's part of funnel steps.",
            })
        })
    })

    describe('isSingleSeriesOutput', () => {
        it('returns true for single series without breakdown', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: true })
        })

        it('returns false for multiple series without formula', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: false })
        })

        it('returns true for multiple series with single formula', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    trendsFilter: {
                        formula: 'A + B',
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: true })
        })

        it('returns true for multiple series with single formula in formulas array', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    trendsFilter: {
                        formulas: ['A + B'],
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: true })
        })

        it('returns false for multiple series with multiple formulas', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    trendsFilter: {
                        formulas: ['A + B', 'A - B'],
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: false })
        })

        it('returns false for single series with breakdown', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    breakdownFilter: {
                        breakdown: '$browser',
                        breakdown_type: 'event',
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesOutput: false })
        })
    })

    describe('isSingleSeriesDefinition', () => {
        it('returns true for single series without breakdown', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesDefinition: true })
        })

        it('returns false for multiple series', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$autocapture',
                            event: '$autocapture',
                        },
                    ],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesDefinition: false })
        })

        it('returns true for single series WITH breakdown (unlike isSingleSeriesOutput)', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    breakdownFilter: {
                        breakdown: '$browser',
                        breakdown_type: 'event',
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesDefinition: true })
        })

        it('returns true for single series WITH breakdowns array', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    breakdownFilter: {
                        breakdowns: [
                            {
                                property: '$browser',
                                type: 'event',
                            },
                        ],
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesDefinition: true })
        })

        it('returns true for multiple series with single formula', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$autocapture',
                            event: '$autocapture',
                        },
                    ],
                    trendsFilter: {
                        formula: 'A + B',
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isSingleSeriesDefinition: true })
        })
    })

    describe('isBreakdownSeries', () => {
        it('returns false without breakdown filter', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isBreakdownSeries: false })
        })

        it('returns true with singular breakdown object', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                    breakdownFilter: {
                        breakdown: '$browser',
                        breakdown_type: 'event',
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isBreakdownSeries: true })
        })

        it('returns true with breakdowns array', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                    breakdownFilter: {
                        breakdowns: [{ property: '$browser', type: 'event' }],
                    },
                } as Partial<TrendsQuery>)
            }).toMatchValues({ isBreakdownSeries: true })
        })
    })

    describe('supportsCompare', () => {
        const setFunnelVizType = (funnelVizType: FunnelVizType): void => {
            builtInsightVizDataLogic.actions.updateQuerySource({
                ...funnelsQueryDefault,
                funnelsFilter: { ...funnelsQueryDefault.funnelsFilter, funnelVizType },
            } as FunnelsQuery)
        }

        it.each([
            [FunnelVizType.Steps, true],
            [FunnelVizType.Trends, true],
            [FunnelVizType.TimeToConvert, true],
            // FLOW is excluded — the backend ignores compare for it.
            [FunnelVizType.Flow, false],
        ] as [FunnelVizType, boolean][])('flag on, %s viz → %s', (funnelVizType, expected) => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE]: true,
            })
            setFunnelVizType(funnelVizType)

            expect(builtInsightVizDataLogic.values.supportsCompare).toBe(expected)
        })

        it('flag off → compare unsupported even for steps viz', () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE]: false,
            })
            setFunnelVizType(FunnelVizType.Steps)

            expect(builtInsightVizDataLogic.values.supportsCompare).toBe(false)
        })
    })
})
