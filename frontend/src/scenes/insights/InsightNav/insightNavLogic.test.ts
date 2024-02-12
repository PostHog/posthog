import { expectLogic } from 'kea-test-utils'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

import { useMocks } from '~/mocks/jest'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { InsightVizNode, Node, NodeKind } from '~/queries/schema'
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
                    cachedInsight: { filters: { insight: InsightType.FUNNELS } },
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

            // it('stores series from retention entities', async () => {
            //     await expectLogic(logic, () => {
            //         builtInsightDataLogic.actions.setQuery(retentionQuery)
            //     }).toMatchValues({
            //         queryPropertyCache: expect.objectContaining({
            //             series: [
            //                 {
            //                     event: 'target',
            //                     kind: 'EventsNode',
            //                     math: 'total',
            //                     name: 'target',
            //                 },
            //                 {
            //                     event: 'returning',
            //                     kind: 'EventsNode',
            //                     math: 'total',
            //                     name: 'returning',
            //                 },
            //             ],
            //         }),
            //     })
            // })

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
        })
    })
})
