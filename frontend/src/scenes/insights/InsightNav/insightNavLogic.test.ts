import { expectLogic } from 'kea-test-utils'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { FunnelsQuery, InsightVizNode, Node, NodeKind, TrendsQuery } from '~/queries/schema'
import { initKeaTests } from '~/test/init'
import { FunnelVizType, InsightLogicProps, InsightShortId, InsightType, StepOrderValue } from '~/types'

import { insightDataLogic } from '../insightDataLogic'

describe('insightNavLogic', () => {
    let logic: ReturnType<typeof insightNavLogic.build>
    let builtInsightLogic: ReturnType<typeof insightLogic.build>
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>

    describe('active view', () => {
        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/projects/:team/insights/trend/': async () => {
                        return [200, { result: ['result from api'] }]
                    },
                },
                post: {
                    '/api/projects/:team/insights/funnel/': { result: ['result from api'] },
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })

            const insightLogicProps: InsightLogicProps = {
                dashboardItemId: 'new',
            }
            builtInsightLogic = insightLogic(insightLogicProps)
            builtInsightLogic.mount()
            builtInsightDataLogic = insightDataLogic(insightLogicProps)
            builtInsightDataLogic.mount()
            logic = insightNavLogic(insightLogicProps)
            logic.mount()
        })

        it('has a default of trends', async () => {
            await expectLogic(logic).toMatchValues({
                activeView: InsightType.TRENDS,
            })
        })

        it('can set the active view to TRENDS which sets the query', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                logic.actions.setActiveView(InsightType.TRENDS)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { ...nodeKindToDefaultQuery[NodeKind.TrendsQuery], filterTestAccounts: true },
                },
            })
        })

        it('can set the active view to FUNNEL which sets the filters differently', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                logic.actions.setActiveView(InsightType.FUNNELS)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...nodeKindToDefaultQuery[NodeKind.FunnelsQuery],
                        filterTestAccounts: true,
                        series: [
                            {
                                event: '$pageview',
                                kind: 'EventsNode',
                                name: '$pageview',
                            },
                        ],
                    },
                },
            })
        })

        it('can set active view to QUERY', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveView(InsightType.JSON)
            }).toMatchValues({
                activeView: InsightType.JSON,
            })
        })

        describe('filters changing changes active view', () => {
            it('takes view from cached insight filters', async () => {
                const props = {
                    dashboardItemId: 'insight' as InsightShortId,
                    cachedInsight: { query: { kind: NodeKind.InsightVizNode, source: examples.InsightFunnelsQuery } },
                }
                const buildInsightLogicWithCachedInsight = insightLogic(props)
                buildInsightLogicWithCachedInsight.mount()

                const builtInsightNavLogicForTheCachedInsight = insightNavLogic(props)
                builtInsightNavLogicForTheCachedInsight.mount()

                expect(builtInsightNavLogicForTheCachedInsight.values.activeView).toEqual(InsightType.FUNNELS)
            })

            it('does set view from setInsight if filters are overriding', async () => {
                await expectLogic(logic, () => {
                    builtInsightLogic.actions.setInsight(
                        { filters: { insight: InsightType.FUNNELS } },
                        { overrideFilter: true }
                    )
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadInsightSuccess', async () => {
                await expectLogic(logic, () => {
                    builtInsightLogic.actions.loadInsightSuccess({ filters: { insight: InsightType.FUNNELS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })
        })

        describe('query cache', () => {
            const trendsQuery: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                    ],
                    trendsFilter: { showValuesOnSeries: true },
                },
            }
            const funnelsQuery: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageview',
                            event: '$pageview',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            name: '$pageleave',
                            event: '$pageleave',
                        },
                    ],
                    funnelsFilter: {
                        funnelOrderType: StepOrderValue.STRICT,
                        funnelVizType: FunnelVizType.Steps,
                    },
                },
            }
            // const retentionQuery: InsightVizNode = {
            //     kind: NodeKind.InsightVizNode,
            //     source: {
            //         kind: NodeKind.RetentionQuery,
            //         retentionFilter: {
            //             returningEntity: {
            //                 id: 'returning',
            //                 name: 'returning',
            //                 type: 'events',
            //             },
            //             targetEntity: {
            //                 id: 'target',
            //                 name: 'target',
            //                 type: 'events',
            //             },
            //         },
            //     },
            // }

            it('is initialized on mount', async () => {
                await expectLogic(logic).toMatchValues({
                    queryPropertyCache: {
                        ...nodeKindToDefaultQuery[NodeKind.TrendsQuery],
                        commonFilter: {},
                        filterTestAccounts: true,
                    },
                })
            })

            it('stores query updates', async () => {
                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        series: [
                            {
                                event: '$pageview',
                                kind: 'EventsNode',
                                name: '$pageview',
                            },
                        ],
                    }),
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(funnelsQuery)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        series: [
                            {
                                event: '$pageview',
                                kind: 'EventsNode',
                                name: '$pageview',
                            },
                            {
                                event: '$pageleave',
                                kind: 'EventsNode',
                                name: '$pageleave',
                            },
                        ],
                    }),
                })
            })

            it('stores insight filter in commonFilter', async () => {
                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        commonFilter: { showValuesOnSeries: true },
                    }),
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(funnelsQuery)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        commonFilter: {
                            showValuesOnSeries: true,
                            funnelOrderType: 'strict',
                            funnelVizType: 'steps',
                        },
                    }),
                })
            })

            it('updates query when navigating', async () => {
                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })

                await expectLogic(logic, () => {
                    logic.actions.setActiveView(InsightType.LIFECYCLE)
                }).toDispatchActions([
                    logic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'LifecycleQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview' }],
                            filterTestAccounts: true,
                            lifecycleFilter: { showValuesOnSeries: true },
                        },
                    } as Node),
                ])
            })

            it('gets rid of minute when leaving trends', async () => {
                ;(trendsQuery.source as TrendsQuery).interval = 'minute'
                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.LIFECYCLE)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'LifecycleQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview' }],
                            filterTestAccounts: true,
                            interval: 'hour',
                            lifecycleFilter: { showValuesOnSeries: true },
                        },
                    } as Node),
                ])
            })

            it('gets rid of multiple breakdowns when switching from trends to funnels', async () => {
                trendsQuery.source = {
                    ...trendsQuery.source,
                    breakdownFilter: {
                        breakdowns: [
                            { property: 'num', type: 'person', histogram_bin_count: 10 },
                            { property: '$device_type', type: 'event' },
                        ],
                    },
                } as TrendsQuery

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview' }],
                            funnelsFilter: { funnelVizType: 'steps' },
                            filterTestAccounts: true,
                            interval: 'hour',
                            breakdownFilter: {
                                breakdowns: undefined,
                                breakdown: 'num',
                                breakdown_type: 'person',
                                breakdown_histogram_bin_count: 10,
                                breakdown_group_type_index: undefined,
                                breakdown_normalize_url: undefined,
                            },
                        },
                    } as Node),
                ])
            })

            it('keeps multiple breakdowns when switching from funnels to trends', async () => {
                funnelsQuery.source = {
                    ...funnelsQuery.source,
                    breakdownFilter: {
                        breakdowns: [
                            { property: 'num', type: 'person' },
                            { property: '$device_type', type: 'event' },
                        ],
                    },
                } as FunnelsQuery

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(funnelsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [
                                { kind: 'EventsNode', name: '$pageview', event: '$pageview', math: 'total' },
                                { kind: 'EventsNode', name: '$pageleave', event: '$pageleave', math: 'total' },
                            ],
                            trendsFilter: {},
                            filterTestAccounts: true,
                            breakdownFilter: {
                                breakdowns: [
                                    { property: 'num', type: 'person' },
                                    { property: '$device_type', type: 'event' },
                                ],
                            },
                        },
                    } as Node),
                ])
            })

            it('keeps breakdowns when switching between trends and funnels', async () => {
                trendsQuery.source = {
                    ...trendsQuery.source,
                    breakdownFilter: {
                        breakdowns: [
                            { property: '$pathname', type: 'group', normalize_url: true, group_type_index: 0 },
                            { property: '$device_type', type: 'event' },
                        ],
                    },
                } as TrendsQuery

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview' }],
                            funnelsFilter: { funnelVizType: 'steps' },
                            filterTestAccounts: true,
                            interval: 'hour',
                            breakdownFilter: {
                                breakdowns: undefined,
                                breakdown: '$pathname',
                                breakdown_type: 'group',
                                breakdown_group_type_index: 0,
                                breakdown_normalize_url: true,
                            },
                        },
                    } as Node),
                ])

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview', math: 'total' }],
                            trendsFilter: { showValuesOnSeries: true },
                            filterTestAccounts: true,
                            interval: 'hour',
                            breakdownFilter: {
                                breakdowns: undefined,
                                breakdown: '$pathname',
                                breakdown_type: 'group',
                                breakdown_group_type_index: 0,
                                breakdown_normalize_url: true,
                            },
                        },
                    } as Node),
                ])
            })
        })
    })
})
