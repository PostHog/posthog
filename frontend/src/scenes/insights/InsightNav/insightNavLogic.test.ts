import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { useMocks } from '~/mocks/jest'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { DataTableNode, NodeKind } from '~/queries/schema'

describe('insightNavLogic', () => {
    let theInsightLogic: ReturnType<typeof insightLogic.build>
    let theInsightNavLogic: ReturnType<typeof insightNavLogic.build>
    let theFeatureFlagLogic: ReturnType<typeof featureFlagLogic.build>

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

            theFeatureFlagLogic = featureFlagLogic()
            theFeatureFlagLogic.mount()
            theFeatureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HOGQL], {
                [FEATURE_FLAGS.HOGQL]: false,
            })

            const insightLogicProps: InsightLogicProps = {
                dashboardItemId: 'new',
            }
            theInsightLogic = insightLogic(insightLogicProps)
            theInsightLogic.mount()
            theInsightNavLogic = insightNavLogic(insightLogicProps)
            theInsightNavLogic.mount()
        })

        it('has a default of trends', async () => {
            await expectLogic(theInsightNavLogic).toMatchValues({
                activeView: InsightType.TRENDS,
            })
        })

        it('can set the active view to TRENDS which sets the filters', async () => {
            await expectLogic(theInsightLogic, () => {
                theInsightNavLogic.actions.setActiveView(InsightType.TRENDS)
            }).toMatchValues({
                filters: {
                    actions: [],
                    display: 'ActionsLineGraph',
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                            type: 'events',
                        },
                    ],
                    insight: 'TRENDS',
                    interval: 'day',
                },
            })
        })

        it('can set the active view to FUNNEL which sets the filters differently', async () => {
            await expectLogic(theInsightLogic, () => {
                theInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            }).toMatchValues({
                filters: {
                    actions: [],
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                            type: 'events',
                        },
                    ],
                    exclusions: [],
                    funnel_viz_type: 'steps',
                    insight: 'FUNNELS',
                },
            })
        })

        it('clears maybeShowTimeoutMessage when setting active view', async () => {
            theInsightLogic.actions.markInsightTimedOut('a query id')
            await expectLogic(theInsightLogic).toMatchValues({ maybeShowTimeoutMessage: true })
            theInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            await expectLogic(theInsightLogic).toMatchValues({ maybeShowTimeoutMessage: false })
        })

        it('clears maybeShowErrorMessage when setting active view', async () => {
            theInsightLogic.actions.loadInsightFailure('error', { status: 0 })
            await expectLogic(theInsightLogic).toMatchValues({ maybeShowErrorMessage: true })
            theInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            await expectLogic(theInsightLogic).toMatchValues({ maybeShowErrorMessage: false })
        })

        it('clears lastRefresh when setting active view', async () => {
            theInsightLogic.actions.setLastRefresh('123')
            await expectLogic(theInsightLogic).toMatchValues({ lastRefresh: '123' })
            theInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            await expectLogic(theInsightLogic).toFinishAllListeners().toMatchValues({ lastRefresh: null })
        })

        it('clears erroredQueryId when setting active view', async () => {
            theInsightLogic.actions.markInsightErrored('123')
            await expectLogic(theInsightLogic).toMatchValues({ erroredQueryId: '123' })
            theInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            await expectLogic(theInsightLogic).toMatchValues({ erroredQueryId: null })
        })

        it('can set active view to QUERY', async () => {
            await expectLogic(theInsightNavLogic, () => {
                theInsightNavLogic.actions.setActiveView(InsightType.JSON)
            }).toMatchValues({
                activeView: InsightType.JSON,
            })
        })

        describe('filters changing changes active view', () => {
            it('takes view from cached insight filters', async () => {
                const propsWithCachedInsight = {
                    dashboardItemId: 'insight' as InsightShortId,
                    cachedInsight: { filters: { insight: InsightType.FUNNELS } },
                }
                const theInsightLogicWithCachedInsight = insightLogic(propsWithCachedInsight)
                theInsightLogicWithCachedInsight.mount()
                const theInsightNavLogicForTheCachedInsight = insightNavLogic({
                    dashboardItemId: 'insight' as InsightShortId,
                    cachedInsight: { filters: { insight: InsightType.FUNNELS } },
                })
                theInsightNavLogicForTheCachedInsight.mount()
                expect(theInsightNavLogicForTheCachedInsight.values.activeView).toEqual(InsightType.FUNNELS)
            })

            it('does set view from setInsight if filters are overriding', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.setInsight(
                        { filters: { insight: InsightType.FUNNELS } },
                        { overrideFilter: true }
                    )
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadInsightSuccess', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.loadInsightSuccess({ filters: { insight: InsightType.FUNNELS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadResultsSuccess', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.loadResultsSuccess({ filters: { insight: InsightType.FUNNELS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets QUERY view from loadResultsSuccess', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.loadResultsSuccess({
                        filters: {},
                        query: { kind: NodeKind.DataTableNode } as DataTableNode,
                    })
                }).toMatchValues({
                    activeView: InsightType.JSON,
                })
            })
        })
    })
})
