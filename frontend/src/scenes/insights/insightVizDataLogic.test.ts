import { expectLogic } from 'kea-test-utils'

import { FunnelLayout } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { funnelInvalidExclusionError, funnelResult } from 'scenes/funnels/__mocks__/funnelDataLogicMocks'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { funnelsQueryDefault, trendsQueryDefault } from '~/queries/nodes/InsightQuery/defaults'
import {
    ActionsNode,
    EventsNode,
    FunnelsQuery,
    InsightQueryNode,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightModel, InsightShortId, InsightType } from '~/types'

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
    })

    describe('updateDateRange', () => {
        it('updates the date range', async () => {
            // when dateRange is empty
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_from: '-7d',
                    date_to: null,
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
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: null,
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
                            },
                            version: 2,
                        },
                    },
                })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: '-3d',
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
                },
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
                },
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

    describe('isFunnelWithEnoughSteps', () => {
        const queryWithSeries = (series: (ActionsNode | EventsNode)[]): FunnelsQuery => ({
            kind: NodeKind.FunnelsQuery,
            series,
        })

        it('with enough/not enough steps', () => {
            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({
                    kind: NodeKind.RetentionQuery,
                } as InsightQueryNode)
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource(queryWithSeries([]))
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(builtInsightVizDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource(
                    queryWithSeries([{ kind: NodeKind.EventsNode }, { kind: NodeKind.EventsNode }])
                )
            }).toMatchValues({ isFunnelWithEnoughSteps: true })
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

    describe('isSingleSeries', () => {
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
            }).toMatchValues({ isSingleSeries: true })
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
            }).toMatchValues({ isSingleSeries: false })
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
            }).toMatchValues({ isSingleSeries: true })
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
            }).toMatchValues({ isSingleSeries: true })
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
            }).toMatchValues({ isSingleSeries: false })
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
            }).toMatchValues({ isSingleSeries: false })
        })
    })
})
