import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { InsightShortId } from '~/types'

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

        it('updateQuerySource update the query source', () => {
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
})
