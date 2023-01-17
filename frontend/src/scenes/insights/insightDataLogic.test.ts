import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { ChartDisplayType, InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'

const Insight123 = '123' as InsightShortId

describe('insightDataLogic', () => {
    let logic: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        initKeaTests()
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
        })
    })
})
