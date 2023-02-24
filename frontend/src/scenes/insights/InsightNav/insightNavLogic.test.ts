import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { useMocks } from '~/mocks/jest'

describe('insightNavLogic', () => {
    let theInsightLogic: ReturnType<typeof insightLogic.build>
    let theInsightNavLogic: ReturnType<typeof insightNavLogic.build>

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
                    filter_test_accounts: false,
                    insight: 'TRENDS',
                    interval: 'day',
                    properties: [],
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

            it('sets view from setFilters', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.setFilters({ insight: InsightType.FUNNELS })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('does not set view from setInsight if filters not overriding', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.setInsight({ filters: { insight: InsightType.FUNNELS } }, {})
                }).toMatchValues({
                    activeView: InsightType.TRENDS,
                })
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

            it('does not set view from loadInsightSuccess if there is already a filter in state', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.setFilters({ insight: InsightType.FUNNELS })
                    theInsightLogic.actions.loadInsightSuccess({ filters: { insight: InsightType.PATHS } })
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

            it('does not set view from loadResultsSuccess if there is already a filter in state', async () => {
                await expectLogic(theInsightNavLogic, () => {
                    theInsightLogic.actions.setFilters({ insight: InsightType.FUNNELS })
                    theInsightLogic.actions.loadResultsSuccess({ filters: { insight: InsightType.PATHS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })
        })
    })
})
