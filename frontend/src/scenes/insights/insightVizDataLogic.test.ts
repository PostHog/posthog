import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { ChartDisplayType, InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { useMocks } from '~/mocks/jest'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

const Insight123 = '123' as InsightShortId

describe('insightVizDataLogic', () => {
    let theInsightVizDataLogic: ReturnType<typeof insightVizDataLogic.build>
    let theInsightDataLogic: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights/trend': [],
            },
        })
        initKeaTests()
    })

    describe('manages query source state', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            theInsightVizDataLogic = insightVizDataLogic(props)
            theInsightDataLogic = insightDataLogic(props)
            theInsightDataLogic.mount()
        })

        it('updateQuerySource updates the query source', () => {
            expectLogic(theInsightDataLogic, () => {
                theInsightVizDataLogic.actions.updateQuerySource({ filterTestAccounts: true })
            }).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        filterTestAccounts: true,
                    }),
                }),
            })

            expect(theInsightVizDataLogic.values.querySource).toMatchObject({ filterTestAccounts: true })
        })
    })

    describe('manages insight filter state', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            theInsightDataLogic = insightDataLogic(props)
            theInsightDataLogic.mount()
        })

        it('updateInsightFilter updates the insight filter', () => {
            expectLogic(theInsightDataLogic, () => {
                theInsightVizDataLogic.actions.updateInsightFilter({ display: ChartDisplayType.ActionsAreaGraph })
            }).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        trendsFilter: expect.objectContaining({
                            display: 'ActionsAreaGraph',
                        }),
                    }),
                }),
            })

            expect(theInsightVizDataLogic.values.insightFilter).toMatchObject({ display: 'ActionsAreaGraph' })
        })
    })
})
