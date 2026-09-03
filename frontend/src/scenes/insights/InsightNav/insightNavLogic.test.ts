import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { LATEST_VERSIONS } from '~/queries/latest-versions'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import {
    EventsQuery,
    FunnelsQuery,
    InsightVizNode,
    NodeKind,
    Node,
    ProductKey,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'
import {
    BaseMathType,
    ChartDisplayType,
    FunnelVizType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
    RetentionEntity,
    StepOrderValue,
} from '~/types'

import { PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/product_analytics/frontend/constants'

import { insightDataLogic } from '../insightDataLogic'

describe('insightNavLogic', () => {
    let logic: ReturnType<typeof insightNavLogic.build>
    let builtInsightLogic: ReturnType<typeof insightLogic.build>
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>

    describe('active view', () => {
        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/insights/trend/': async () => {
                        return [200, { result: ['result from api'] }]
                    },
                },
                post: {
                    '/api/environments/:team_id/insights/funnel/': { result: ['result from api'] },
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
                query: setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...nodeKindToDefaultQuery[NodeKind.TrendsQuery],
                        filterTestAccounts: true,
                        tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                }),
            })
        })

        it('can set the active view to FUNNEL which sets the filters differently', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                logic.actions.setActiveView(InsightType.FUNNELS)
            }).toMatchValues({
                query: setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...nodeKindToDefaultQuery[NodeKind.FunnelsQuery],
                        filterTestAccounts: true,
                        series: [
                            {
                                event: '$pageview',
                                kind: 'EventsNode',
                                name: 'Pageview',
                            },
                        ],
                        tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                }),
            })
        })

        it('tags queries with product_analytics productKey', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                logic.actions.setActiveView(InsightType.TRENDS)
            })

            const query = builtInsightDataLogic.values.query as InsightVizNode
            expect(query.source?.tags?.productKey).toEqual(ProductKey.PRODUCT_ANALYTICS)
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

            it('does set view from setInsight when overriding the query', async () => {
                await expectLogic(logic, () => {
                    builtInsightLogic.actions.setInsight({ query: examples.InsightFunnels }, { overrideQuery: true })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadInsightSuccess', async () => {
                await expectLogic(logic, () => {
                    builtInsightLogic.actions.loadInsightSuccess({
                        query: examples.InsightFunnels,
                    } as QueryBasedInsightModel)
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })
        })

        describe('journeys tab visibility', () => {
            it('hides the journeys tab without the flag', () => {
                expect(logic.values.tabs.map((tab) => tab.type)).not.toContain(InsightType.JOURNEYS)
            })

            it('shows the journeys tab with the flag on, between paths and stickiness', () => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_V2]: true })
                const tabTypes = logic.values.tabs.map((tab) => tab.type)
                expect(tabTypes.indexOf(InsightType.JOURNEYS)).toEqual(tabTypes.indexOf(InsightType.PATHS) + 1)
                expect(tabTypes.indexOf(InsightType.JOURNEYS)).toEqual(tabTypes.indexOf(InsightType.STICKINESS) - 1)
            })

            it('shows the journeys tab without the flag when viewing a journeys insight, so links never dead-end', () => {
                const props = {
                    dashboardItemId: 'insight-v2' as InsightShortId,
                    cachedInsight: {
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: { kind: NodeKind.PathsV2Query },
                        } as Node,
                    },
                }
                insightLogic(props).mount()
                const builtLogic = insightNavLogic(props)
                builtLogic.mount()

                expect(builtLogic.values.activeView).toEqual(InsightType.JOURNEYS)
                expect(builtLogic.values.tabs.map((tab) => tab.type)).toContain(InsightType.JOURNEYS)
            })

            it('keeps the journeys filter when switching away and back', async () => {
                const journeysQuery: InsightVizNode = {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.PathsV2Query,
                        pathsV2Filter: {
                            stepSources: [{ event: '$screen', namingProperty: '$screen_name' }],
                        },
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(journeysQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.JOURNEYS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'PathsV2Query',
                        pathsV2Filter: {
                            stepSources: [{ event: '$screen', namingProperty: '$screen_name' }],
                        },
                    },
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

            it('is initialized on mount', async () => {
                await expectLogic(logic).toMatchValues({
                    queryPropertyCache: setLatestVersionsOnQuery({
                        ...nodeKindToDefaultQuery[NodeKind.TrendsQuery],
                        commonFilter: {},
                        commonFilterTrendsStickiness: {},
                        filterTestAccounts: true,
                    }),
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
                            version: LATEST_VERSIONS[NodeKind.LifecycleQuery],
                            lifecycleFilter: { showValuesOnSeries: true },
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                    } as Node),
                ])
            })

            it('does not restore removed global filters when switching insight types', async () => {
                const trendsQueryWithGlobalFilters: InsightVizNode<TrendsQuery> = {
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
                        properties: [
                            {
                                key: '$browser',
                                type: PropertyFilterType.Event,
                                value: 'Chrome',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        trendsFilter: { showValuesOnSeries: true },
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithGlobalFilters)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        properties: [
                            expect.objectContaining({
                                key: '$browser',
                                value: 'Chrome',
                            }),
                        ],
                    }),
                })

                await expectLogic(logic, () => {
                    const trendsQueryWithoutGlobalFilters: InsightVizNode<TrendsQuery> = {
                        ...trendsQueryWithGlobalFilters,
                        source: {
                            ...trendsQueryWithGlobalFilters.source,
                            properties: undefined,
                        },
                    }

                    builtInsightDataLogic.actions.setQuery(trendsQueryWithoutGlobalFilters)
                }).toMatchValues({
                    queryPropertyCache: expect.not.objectContaining({
                        properties: expect.anything(),
                    }),
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                expect((builtInsightDataLogic.values.query as InsightVizNode).source).not.toMatchObject({
                    properties: expect.anything(),
                })
            })

            it('keeps filterTestAccounts disabled when switching insight types after it was turned off', async () => {
                // Mirrors the DW-series flow: the trends query had filterTestAccounts auto-disabled
                // (set to explicit false). Switching to Funnels must not re-enable it from the team default.
                const trendsQueryWithFilterDisabled: InsightVizNode<TrendsQuery> = {
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
                        filterTestAccounts: false,
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithFilterDisabled)
                }).toMatchValues({
                    queryPropertyCache: expect.objectContaining({
                        filterTestAccounts: false,
                    }),
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                expect((builtInsightDataLogic.values.query as InsightVizNode).source).toMatchObject({
                    kind: NodeKind.FunnelsQuery,
                    filterTestAccounts: false,
                })
            })

            it('keeps trends-only filters when switching away and back', async () => {
                const trendsQueryWithTrendLine: InsightVizNode = {
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
                        trendsFilter: {
                            showTrendLines: true,
                        },
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithTrendLine)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        trendsFilter: expect.objectContaining({
                            showTrendLines: true,
                        }),
                    },
                })
            })

            it.each([
                ['switching away from trends and back', [InsightType.FUNNELS]],
                ['switching through multiple tabs', [InsightType.FUNNELS, InsightType.LIFECYCLE]],
            ] as const)('preserves series math when %s', async (_, intermediateViews) => {
                const trendsQueryWithUniqueUsers: InsightVizNode = {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                name: '$pageview',
                                event: '$pageview',
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithUniqueUsers)
                })

                for (const view of intermediateViews) {
                    await expectLogic(builtInsightDataLogic, () => {
                        logic.actions.setActiveView(view)
                    }).toFinishAllListeners()
                }

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        series: [expect.objectContaining({ math: BaseMathType.UniqueUsers })],
                    },
                })
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
                            version: LATEST_VERSIONS[NodeKind.LifecycleQuery],
                            interval: 'hour',
                            lifecycleFilter: { showValuesOnSeries: true },
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
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
                            funnelsFilter: { funnelVizType: 'steps', showValuesOnSeries: true },
                            filterTestAccounts: true,
                            version: LATEST_VERSIONS[NodeKind.FunnelsQuery],
                            interval: 'hour',
                            breakdownFilter: {
                                breakdowns: undefined,
                                breakdown: 'num',
                                breakdown_type: 'person',
                                breakdown_histogram_bin_count: 10,
                                breakdown_group_type_index: undefined,
                                breakdown_normalize_url: undefined,
                            },
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
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
                    // can't use setLatestVersionsOnQuery here: toDispatchActions compares actions via
                    // JSON.stringify, so `version` must sit exactly where the logic inserts it
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
                            version: LATEST_VERSIONS[NodeKind.TrendsQuery],
                            breakdownFilter: {
                                breakdowns: [
                                    { property: 'num', type: 'person' },
                                    { property: '$device_type', type: 'event' },
                                ],
                            },
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                    } as Node),
                ])
            })

            it('keeps breakdowns when switching between trends and funnels', async () => {
                trendsQuery.source = setLatestVersionsOnQuery({
                    ...trendsQuery.source,
                    breakdownFilter: {
                        breakdowns: [
                            { property: '$pathname', type: 'group', normalize_url: true, group_type_index: 0 },
                            { property: '$device_type', type: 'event' },
                        ],
                    },
                } as TrendsQuery)

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
                            funnelsFilter: { funnelVizType: 'steps', showValuesOnSeries: true },
                            filterTestAccounts: true,
                            version: LATEST_VERSIONS[NodeKind.FunnelsQuery],
                            interval: 'hour',
                            breakdownFilter: {
                                breakdowns: undefined,
                                breakdown: '$pathname',
                                breakdown_type: 'group',
                                breakdown_group_type_index: 0,
                                breakdown_normalize_url: true,
                            },
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                    } as Node),
                ])

                // Switch back to Trends — full multi-breakdown should be restored
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const restoredQuery = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(restoredQuery.breakdownFilter?.breakdowns).toEqual([
                    { property: '$pathname', type: 'group', normalize_url: true, group_type_index: 0 },
                    { property: '$device_type', type: 'event' },
                ])
            })

            it('does not carry trends-only display settings into funnels', async () => {
                const trendsQueryWithDisplay: InsightVizNode = setLatestVersionsOnQuery({
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
                        interval: 'hour',
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBar,
                            showPercentStackView: true,
                            showValuesOnSeries: true,
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithDisplay)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toDispatchActions([
                    builtInsightDataLogic.actionCreators.setQuery({
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [{ kind: 'EventsNode', name: '$pageview', event: '$pageview' }],
                            funnelsFilter: { funnelVizType: 'steps', showValuesOnSeries: true },
                            filterTestAccounts: true,
                            version: LATEST_VERSIONS[NodeKind.FunnelsQuery],
                            interval: 'hour',
                            tags: PRODUCT_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                    } as Node),
                ])
            })

            it('does not carry showValuesOnSeries into retention', async () => {
                const funnelsQueryWithValuesOnSeries: InsightVizNode = {
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
                            showValuesOnSeries: true,
                        },
                    },
                }

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(funnelsQueryWithValuesOnSeries)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'RetentionQuery',
                        filterTestAccounts: true,
                    },
                })
                expect((builtInsightDataLogic.values.query as InsightVizNode).source).not.toMatchObject({
                    retentionFilter: expect.objectContaining({ showValuesOnSeries: true }),
                })
            })

            it('SCRATCH count+math', async () => {
                const trendsQuery: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                name: 'a_event',
                                event: 'a_event',
                                math: BaseMathType.UniqueUsers,
                            },
                            { kind: NodeKind.EventsNode, name: 'b_event', event: 'b_event' },
                            { kind: NodeKind.EventsNode, name: 'c_event', event: 'c_event' },
                        ],
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const back = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                // eslint-disable-next-line no-console
                console.log('SCRATCH after round trip:', JSON.stringify(back.series))
                expect(back.series).toHaveLength(3)
            })

            it('keeps every trends series and its math through a retention round trip', async () => {
                const trendsQuery: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                name: 'a_event',
                                event: 'a_event',
                                math: BaseMathType.UniqueUsers,
                            },
                            { kind: NodeKind.EventsNode, name: 'b_event', event: 'b_event' },
                            { kind: NodeKind.EventsNode, name: 'c_event', event: 'c_event' },
                        ],
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                // Retention holds a single target entity, so the series beyond the first only survive
                // in the cache — dropping them here silently deleted the rest of the insight.
                const backToTrends = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(backToTrends.series).toMatchObject([
                    { event: 'a_event', math: BaseMathType.UniqueUsers },
                    { event: 'b_event' },
                    { event: 'c_event' },
                ])
            })

            it('carries a funnel event into retention as a targetEntity in the right shape', async () => {
                const funnelsQuery: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [
                            { kind: NodeKind.EventsNode, name: 'signed_up', event: 'signed_up' },
                            { kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' },
                        ],
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(funnelsQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()

                const retentionSource = (builtInsightDataLogic.values.query as InsightVizNode).source as RetentionQuery
                expect(retentionSource.retentionFilter?.targetEntity).toEqual({
                    kind: NodeKind.EventsNode,
                    type: 'events',
                    id: 'signed_up',
                    name: 'signed_up',
                })
                // A RetentionEntity forbids the EventsNode `event` key, which was a 400 before
                expect(retentionSource.retentionFilter?.targetEntity).not.toHaveProperty('event')
            })

            it('carries a retention target entity back into a series on switch away', async () => {
                const retentionQuery: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.RetentionQuery,
                        retentionFilter: {
                            targetEntity: {
                                kind: NodeKind.EventsNode,
                                type: 'events',
                                id: 'purchase',
                                name: 'purchase',
                            },
                            returningEntity: {
                                kind: NodeKind.EventsNode,
                                type: 'events',
                                id: 'purchase',
                                name: 'purchase',
                            },
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(retentionQuery)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const trendsSource = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsSource.series).toMatchObject([
                    { kind: NodeKind.EventsNode, event: 'purchase', name: 'purchase' },
                ])
            })

            it('preserves a data warehouse retention target through a trends round trip', async () => {
                const dwhEntity: RetentionEntity = {
                    type: 'data_warehouse',
                    id: 'stripe_customers',
                    name: 'stripe_customers',
                    table_name: 'stripe_customers',
                    timestamp_field: 'created_at',
                    aggregation_target_field: 'customer_id',
                }
                const retentionDwh: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.RetentionQuery,
                        retentionFilter: { targetEntity: dwhEntity, returningEntity: dwhEntity },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(retentionDwh)
                })

                // Switching to trends must not fabricate a series event named after the warehouse table.
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()
                const trendsSource = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsSource.series).not.toContainEqual(expect.objectContaining({ event: 'stripe_customers' }))

                // Switching back must keep the warehouse target intact rather than replacing it with an event.
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()
                const retentionSource = (builtInsightDataLogic.values.query as InsightVizNode).source as RetentionQuery
                expect(retentionSource.retentionFilter?.targetEntity).toMatchObject({
                    type: 'data_warehouse',
                    table_name: 'stripe_customers',
                })
                expect(retentionSource.retentionFilter?.returningEntity).toMatchObject({
                    type: 'data_warehouse',
                    table_name: 'stripe_customers',
                })
            })

            it('keeps event property filters on a retention target through a trends round trip', async () => {
                const targetEntity: RetentionEntity = {
                    kind: NodeKind.EventsNode,
                    type: 'events',
                    id: 'purchase',
                    name: 'purchase',
                    properties: [
                        {
                            key: '$browser',
                            type: PropertyFilterType.Event,
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                        },
                    ],
                }
                const retentionFiltered: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.RetentionQuery,
                        retentionFilter: { targetEntity, returningEntity: targetEntity },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(retentionFiltered)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()

                // Without copying `properties` across the conversion the target would return unfiltered,
                // silently widening the retention count.
                const retentionSource = (builtInsightDataLogic.values.query as InsightVizNode).source as RetentionQuery
                expect(retentionSource.retentionFilter?.targetEntity?.properties).toEqual([
                    expect.objectContaining({ key: '$browser', value: 'Chrome' }),
                ])
            })

            it('does not carry a trends-only display into stickiness', async () => {
                const trendsPie: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                        trendsFilter: { display: ChartDisplayType.ActionsPie },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsPie)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.STICKINESS)
                }).toFinishAllListeners()

                const stickinessSource = (builtInsightDataLogic.values.query as InsightVizNode)
                    .source as StickinessQuery
                expect(stickinessSource.stickinessFilter?.display).toBeUndefined()
            })

            it('preserves multiple breakdowns through round-trip via single-breakdown type', async () => {
                const trendsWithMultipleBreakdowns: InsightVizNode = setLatestVersionsOnQuery({
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
                        breakdownFilter: {
                            breakdowns: [
                                { property: '$browser', type: 'event' },
                                { property: '$os', type: 'event' },
                                { property: '$device_type', type: 'event' },
                            ],
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithMultipleBreakdowns)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                const funnelsQuery = (builtInsightDataLogic.values.query as InsightVizNode).source as FunnelsQuery
                expect(funnelsQuery.breakdownFilter?.breakdown).toBe('$browser')
                expect(funnelsQuery.breakdownFilter?.breakdowns).toBeUndefined()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const trendsQuery = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsQuery.breakdownFilter?.breakdowns).toEqual([
                    { property: '$browser', type: 'event' },
                    { property: '$os', type: 'event' },
                    { property: '$device_type', type: 'event' },
                ])
            })

            it('restores original breakdowns on round-trip even after edits on intermediate type', async () => {
                const trendsWithMultipleBreakdowns: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                        breakdownFilter: {
                            breakdowns: [
                                { property: '$browser', type: 'event' },
                                { property: '$os', type: 'event' },
                            ],
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithMultipleBreakdowns)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                // User edits the single-breakdown while on Funnels
                const currentFunnel = (builtInsightDataLogic.values.query as InsightVizNode).source as FunnelsQuery
                await expectLogic(builtInsightDataLogic, () => {
                    builtInsightDataLogic.actions.setQuery({
                        kind: NodeKind.InsightVizNode,
                        source: {
                            ...currentFunnel,
                            breakdownFilter: { ...currentFunnel.breakdownFilter, breakdown: '$device_type' },
                        },
                    } as InsightVizNode)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                // Original multi-breakdown wins over the edit made on Funnels
                const trendsQuery = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsQuery.breakdownFilter?.breakdowns).toEqual([
                    { property: '$browser', type: 'event' },
                    { property: '$os', type: 'event' },
                ])
            })

            it('restores minute interval on round-trip even after edits on intermediate type', async () => {
                const trendsWithMinute: InsightVizNode = setLatestVersionsOnQuery({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
                        interval: 'minute',
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithMinute)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                // User edits interval while on Funnels
                const currentFunnel = (builtInsightDataLogic.values.query as InsightVizNode).source as FunnelsQuery
                await expectLogic(builtInsightDataLogic, () => {
                    builtInsightDataLogic.actions.setQuery({
                        kind: NodeKind.InsightVizNode,
                        source: { ...currentFunnel, interval: 'day' },
                    } as InsightVizNode)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const trendsQuery = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsQuery.interval).toBe('minute')
            })

            it('preserves breakdownFilter through round-trip via unsupported type', async () => {
                const trendsWithBreakdown: InsightVizNode = setLatestVersionsOnQuery({
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
                        breakdownFilter: {
                            breakdown: '$browser',
                            breakdown_type: 'event',
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithBreakdown)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.STICKINESS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.not.objectContaining({ breakdownFilter: expect.anything() }),
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.objectContaining({
                        kind: 'TrendsQuery',
                        breakdownFilter: {
                            breakdown: '$browser',
                            breakdown_type: 'event',
                        },
                    }),
                })
            })

            it('truncates multi-breakdowns on multi-hop transition through unsupported type back to funnels', async () => {
                const trendsWithMultipleBreakdowns: InsightVizNode = setLatestVersionsOnQuery({
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
                        breakdownFilter: {
                            breakdowns: [
                                { property: '$browser', type: 'event' },
                                { property: '$os', type: 'event' },
                            ],
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithMultipleBreakdowns)
                })

                // Trends → Funnels (truncates to single)
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                const funnelsQuery1 = (builtInsightDataLogic.values.query as InsightVizNode).source as FunnelsQuery
                expect(funnelsQuery1.breakdownFilter?.breakdown).toBe('$browser')
                expect(funnelsQuery1.breakdownFilter?.breakdowns).toBeUndefined()

                // Funnels → Lifecycle (no breakdown support, cached)
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.LIFECYCLE)
                }).toFinishAllListeners()

                // Lifecycle → Funnels (must still truncate, not leak full breakdowns array)
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                const funnelsQuery2 = (builtInsightDataLogic.values.query as InsightVizNode).source as FunnelsQuery
                expect(funnelsQuery2.breakdownFilter?.breakdown).toBe('$browser')
                expect(funnelsQuery2.breakdownFilter?.breakdowns).toBeUndefined()
            })

            it('preserves compareFilter through round-trip via unsupported type', async () => {
                const trendsWithCompare: InsightVizNode = setLatestVersionsOnQuery({
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
                        compareFilter: { compare: true },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithCompare)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.not.objectContaining({ compareFilter: expect.anything() }),
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.objectContaining({
                        kind: 'TrendsQuery',
                        compareFilter: { compare: true },
                    }),
                })
            })

            it('preserves interval through round-trip via type with no interval support', async () => {
                const trendsWithInterval: InsightVizNode = setLatestVersionsOnQuery({
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
                        interval: 'week',
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithInterval)
                })

                // Paths has no interval capability
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.PATHS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.not.objectContaining({ interval: expect.anything() }),
                })

                // Switch back — interval should be restored
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: expect.objectContaining({
                        kind: 'TrendsQuery',
                        interval: 'week',
                    }),
                })
            })

            it('filters breakdowns to person/event types when switching to retention', async () => {
                const trendsWithGroupBreakdown: InsightVizNode = setLatestVersionsOnQuery({
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
                        breakdownFilter: {
                            breakdowns: [
                                { property: '$browser', type: 'event' },
                                { property: 'company', type: 'group', group_type_index: 0 },
                                { property: 'email', type: 'person' },
                            ],
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsWithGroupBreakdown)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.RETENTION)
                }).toFinishAllListeners()

                const retentionQuery = (builtInsightDataLogic.values.query as InsightVizNode).source
                expect(retentionQuery).toMatchObject({
                    kind: 'RetentionQuery',
                    breakdownFilter: {
                        breakdowns: [
                            { property: '$browser', type: 'event' },
                            { property: 'email', type: 'person' },
                        ],
                    },
                })
            })

            it('keeps display when switching from trends to stickiness', async () => {
                const trendsQueryForStickiness: InsightVizNode = setLatestVersionsOnQuery({
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
                        interval: 'hour',
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBar,
                            showValuesOnSeries: true,
                        },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryForStickiness)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.STICKINESS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'StickinessQuery',
                        filterTestAccounts: true,
                        interval: 'hour',
                        stickinessFilter: expect.objectContaining({
                            display: ChartDisplayType.ActionsBar,
                            showValuesOnSeries: true,
                        }),
                    },
                })
            })

            it('normalizes the ActionsStackedBar alias when switching from trends to stickiness', async () => {
                const trendsQueryWithAlias: InsightVizNode = setLatestVersionsOnQuery({
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
                        // ActionsStackedBar reaches this path only via the API/MCP; the UI never emits it.
                        trendsFilter: { display: ChartDisplayType.ActionsStackedBar },
                    },
                })

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(trendsQueryWithAlias)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.STICKINESS)
                }).toFinishAllListeners()

                const stickinessSource = (builtInsightDataLogic.values.query as InsightVizNode)
                    .source as StickinessQuery
                expect(stickinessSource.stickinessFilter?.display).toEqual(ChartDisplayType.ActionsBar)
            })

            const dataWarehouseTestCases: {
                label: string
                source: InsightVizNode['source']
                targetView: InsightType
                expectedSource: Record<string, any>
            }[] = [
                {
                    label: 'trends DW to funnels',
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.DataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                distinct_id_field: 'customer_id',
                            },
                        ],
                    },
                    targetView: InsightType.FUNNELS,
                    expectedSource: {
                        kind: NodeKind.FunnelsQuery,
                        series: [
                            {
                                kind: NodeKind.FunnelsDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                            },
                        ],
                        funnelsFilter: { funnelVizType: FunnelVizType.Steps },
                    },
                },
                {
                    label: 'trends DW to lifecycle',
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.DataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                distinct_id_field: 'customer_id',
                            },
                        ],
                    },
                    targetView: InsightType.LIFECYCLE,
                    expectedSource: {
                        kind: NodeKind.LifecycleQuery,
                        series: [
                            {
                                kind: NodeKind.LifecycleDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                                created_at_field: 'created_at',
                            },
                        ],
                    },
                },
                {
                    label: 'funnels DW to trends',
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [
                            {
                                kind: NodeKind.FunnelsDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                            },
                        ],
                        funnelsFilter: { funnelVizType: FunnelVizType.Steps },
                    },
                    targetView: InsightType.TRENDS,
                    expectedSource: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.DataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                distinct_id_field: 'customer_id',
                            },
                        ],
                    },
                },
                {
                    label: 'funnels DW to lifecycle',
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [
                            {
                                kind: NodeKind.FunnelsDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                id_field: 'id',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                            },
                        ],
                        funnelsFilter: { funnelVizType: FunnelVizType.Steps },
                    },
                    targetView: InsightType.LIFECYCLE,
                    expectedSource: {
                        kind: NodeKind.LifecycleQuery,
                        series: [
                            {
                                kind: NodeKind.LifecycleDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                                created_at_field: 'created_at',
                            },
                        ],
                    },
                },
                {
                    label: 'lifecycle DW to trends',
                    source: {
                        kind: NodeKind.LifecycleQuery,
                        series: [
                            {
                                kind: NodeKind.LifecycleDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                                created_at_field: 'created_at',
                            },
                        ],
                    },
                    targetView: InsightType.TRENDS,
                    expectedSource: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.DataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                distinct_id_field: 'customer_id',
                            },
                        ],
                    },
                },
                {
                    label: 'lifecycle DW to funnels',
                    source: {
                        kind: NodeKind.LifecycleQuery,
                        series: [
                            {
                                kind: NodeKind.LifecycleDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                                created_at_field: 'created_at',
                            },
                        ],
                    },
                    targetView: InsightType.FUNNELS,
                    expectedSource: {
                        kind: NodeKind.FunnelsQuery,
                        series: [
                            {
                                kind: NodeKind.FunnelsDataWarehouseNode,
                                id: 'warehouse_orders',
                                name: 'Warehouse orders',
                                table_name: 'warehouse_orders',
                                timestamp_field: 'created_at',
                                aggregation_target_field: 'customer_id',
                            },
                        ],
                        funnelsFilter: { funnelVizType: 'steps' },
                    },
                },
            ]

            it.each(dataWarehouseTestCases)('converts $label', async ({ source, targetView, expectedSource }) => {
                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery({
                        kind: NodeKind.InsightVizNode,
                        source,
                    } as any)
                })

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(targetView)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    kind: NodeKind.InsightVizNode,
                    source: expectedSource,
                })
            })

            const dataTableSeedingCases: {
                label: string
                source: Partial<EventsQuery>
                targetView: InsightType
                expectedSource: Record<string, any>
            }[] = [
                {
                    label: 'single event + date range + properties',
                    source: {
                        event: '$pageview',
                        after: '-180d',
                        properties: [
                            {
                                key: 'email',
                                value: 'test@example.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                    targetView: InsightType.TRENDS,
                    expectedSource: {
                        kind: NodeKind.TrendsQuery,
                        dateRange: { date_from: '-180d' },
                        properties: [
                            {
                                key: 'email',
                                value: 'test@example.com',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
                    },
                },
                {
                    label: 'events[] seeds multi-series',
                    source: { events: ['$pageview', '$autocapture'] },
                    targetView: InsightType.TRENDS,
                    expectedSource: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                            { kind: NodeKind.EventsNode, event: '$autocapture', name: '$autocapture' },
                        ],
                    },
                },
                {
                    label: 'before-only seeds date_to',
                    source: { before: '2026-01-01T00:00:00Z' },
                    targetView: InsightType.TRENDS,
                    expectedSource: { dateRange: { date_to: '2026-01-01T00:00:00Z' } },
                },
            ]

            it.each(dataTableSeedingCases)(
                'seeds cache from DataTable EventsQuery: $label',
                async ({ source, targetView, expectedSource }) => {
                    const dataTableQuery: Node = {
                        kind: NodeKind.DataTableNode,
                        source: { kind: NodeKind.EventsQuery, select: ['*'], ...source },
                    } as Node

                    await expectLogic(logic, () => {
                        builtInsightDataLogic.actions.setQuery(dataTableQuery)
                    }).toFinishAllListeners()

                    await expectLogic(builtInsightDataLogic, () => {
                        logic.actions.setActiveView(targetView)
                    }).toFinishAllListeners()

                    expect(builtInsightDataLogic.values.query).toMatchObject({
                        kind: NodeKind.InsightVizNode,
                        source: expectedSource,
                    })
                }
            )

            it('cleans seeded series through the funnels capability cleaner', async () => {
                const dataTableQuery: Node = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: ['*'],
                        event: '$pageview',
                    },
                } as Node

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(dataTableQuery)
                }).toFinishAllListeners()

                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.FUNNELS)
                }).toFinishAllListeners()

                expect(builtInsightDataLogic.values.query).toMatchObject({
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
                    },
                })
            })

            it('is a no-op when DataTable EventsQuery has no filters', async () => {
                const dataTableQuery: Node = {
                    kind: NodeKind.DataTableNode,
                    source: { kind: NodeKind.EventsQuery, select: ['*'] },
                } as Node

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(dataTableQuery)
                }).toFinishAllListeners()

                // Subsequent tab switch should not blow up and should not carry any filters
                await expectLogic(builtInsightDataLogic, () => {
                    logic.actions.setActiveView(InsightType.TRENDS)
                }).toFinishAllListeners()

                const trendsSource = (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
                expect(trendsSource.dateRange).toBeUndefined()
                expect(trendsSource.properties).toBeUndefined()
            })

            it('does not seed cache when DataTable source is not an EventsQuery', async () => {
                const cacheBefore = logic.values.queryPropertyCache
                const dataTableQuery: Node = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: 'SELECT * FROM events',
                    },
                } as Node

                await expectLogic(logic, () => {
                    builtInsightDataLogic.actions.setQuery(dataTableQuery)
                }).toFinishAllListeners()

                expect(logic.values.queryPropertyCache).toEqual(cacheBefore)
            })
        })
    })
})
