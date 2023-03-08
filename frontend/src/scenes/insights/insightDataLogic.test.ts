import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { ChartDisplayType, InsightLogicProps, InsightShortId, InsightType } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { NodeKind } from '~/queries/schema'
import { useMocks } from '~/mocks/jest'

const Insight123 = '123' as InsightShortId

describe('insightDataLogic', () => {
    let logic: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights/trend': [],
            },
        })
        initKeaTests()
    })

    describe('default query', () => {
        it('defaults to trends', () => {
            const props: InsightLogicProps = { dashboardItemId: 'new' }
            const logic = insightDataLogic(props)
            logic.mount()
            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    kind: NodeKind.InsightVizNode,
                    source: expect.objectContaining({
                        kind: NodeKind.TrendsQuery,
                    }),
                }),
            })
        })

        it('can load from a cached filter-based insight', () => {
            const props: InsightLogicProps = {
                dashboardItemId: 'new',
                cachedInsight: { filters: { insight: InsightType.STICKINESS } },
            }
            const logic = insightDataLogic(props)
            logic.mount()
            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    kind: NodeKind.InsightVizNode,
                    source: expect.objectContaining({
                        kind: NodeKind.StickinessQuery,
                    }),
                }),
            })
        })

        it('can load from a cached query-based insight', () => {
            const props: InsightLogicProps = {
                dashboardItemId: 'new',
                cachedInsight: { query: { kind: NodeKind.DataTableNode } },
            }
            const logic = insightDataLogic(props)
            logic.mount()
            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    kind: NodeKind.DataTableNode,
                }),
            })
        })
    })

    describe('manages query source state', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            logic = insightDataLogic(props)
            logic.mount()
        })

        it('updateQuerySource updates the query source', () => {
            expectLogic(logic, () => {
                logic.actions.updateQuerySource({ filterTestAccounts: true })
            }).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        filterTestAccounts: true,
                    }),
                }),
            })

            expect(logic.values.querySource).toMatchObject({ filterTestAccounts: true })
        })
    })

    describe('manages insight filter state', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            logic = insightDataLogic(props)
            logic.mount()
        })

        it('updateInsightFilter updates the insight filter', () => {
            expectLogic(logic, () => {
                logic.actions.updateInsightFilter({ display: ChartDisplayType.ActionsAreaGraph })
            }).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        trendsFilter: expect.objectContaining({
                            display: 'ActionsAreaGraph',
                        }),
                    }),
                }),
            })

            expect(logic.values.insightFilter).toMatchObject({ display: 'ActionsAreaGraph' })
        })
    })
})
