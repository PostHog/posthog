import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema'
import { insightDataLogic } from '../insightDataLogic'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'

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
                    source: { ...nodeKindToDefaultQuery[NodeKind.FunnelsQuery], filterTestAccounts: true },
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
    })
})
