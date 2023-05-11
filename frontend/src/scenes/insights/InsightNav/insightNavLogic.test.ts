import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { useMocks } from '~/mocks/jest'
import { FEATURE_FLAGS } from 'lib/constants'
import { DataTableNode, NodeKind } from '~/queries/schema'

import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from '../insightDataLogic'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'

describe('insightNavLogic', () => {
    let builtInsightLogic: ReturnType<typeof insightLogic.build>
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let builtInsightNavLogic: ReturnType<typeof insightNavLogic.build>
    let builtFeatureFlagLogic: ReturnType<typeof featureFlagLogic.build>

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

            builtFeatureFlagLogic = featureFlagLogic()
            builtFeatureFlagLogic.mount()
            builtFeatureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.HOGQL], {
                [FEATURE_FLAGS.HOGQL]: false,
            })

            const insightLogicProps: InsightLogicProps = {
                dashboardItemId: 'new',
            }
            builtInsightLogic = insightLogic(insightLogicProps)
            builtInsightLogic.mount()
            builtInsightDataLogic = insightDataLogic(insightLogicProps)
            builtInsightDataLogic.mount()
            builtInsightNavLogic = insightNavLogic(insightLogicProps)
            builtInsightNavLogic.mount()
        })

        it('has a default of trends', async () => {
            await expectLogic(builtInsightNavLogic).toMatchValues({
                activeView: InsightType.TRENDS,
            })
        })

        it('can set the active view to TRENDS which sets the query', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightNavLogic.actions.setActiveView(InsightType.TRENDS)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { ...nodeKindToDefaultQuery[NodeKind.TrendsQuery], filterTestAccounts: true },
                },
            })
        })

        it('can set the active view to FUNNEL which sets the query differently', async () => {
            await expectLogic(builtInsightDataLogic, () => {
                builtInsightNavLogic.actions.setActiveView(InsightType.FUNNELS)
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { ...nodeKindToDefaultQuery[NodeKind.FunnelsQuery], filterTestAccounts: true },
                },
            })
        })

        it('can set active view to QUERY', async () => {
            await expectLogic(builtInsightNavLogic, () => {
                builtInsightNavLogic.actions.setActiveView(InsightType.JSON)
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
                await expectLogic(builtInsightNavLogic, () => {
                    builtInsightLogic.actions.setInsight(
                        { filters: { insight: InsightType.FUNNELS } },
                        { overrideFilter: true }
                    )
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadInsightSuccess', async () => {
                await expectLogic(builtInsightNavLogic, () => {
                    builtInsightLogic.actions.loadInsightSuccess({ filters: { insight: InsightType.FUNNELS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets view from loadResultsSuccess', async () => {
                await expectLogic(builtInsightNavLogic, () => {
                    builtInsightLogic.actions.loadResultsSuccess({ filters: { insight: InsightType.FUNNELS } })
                }).toMatchValues({
                    activeView: InsightType.FUNNELS,
                })
            })

            it('sets QUERY view from loadResultsSuccess', async () => {
                await expectLogic(builtInsightNavLogic, () => {
                    builtInsightLogic.actions.loadResultsSuccess({
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
