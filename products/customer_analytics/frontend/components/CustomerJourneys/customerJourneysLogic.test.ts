import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { customerJourneysLogic } from './customerJourneysLogic'

describe('customerJourneysLogic', () => {
    let logic: ReturnType<typeof customerJourneysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/customer_journeys/': () => [
                    200,
                    { results: [{ id: 'journey-1', name: 'Signup flow', insight: 404 }], count: 1 },
                ],
                '/api/environments/:team_id/insights/404/': () => [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
        logic = customerJourneysLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('leaves activeInsight null when the journey points at a deleted insight', async () => {
        logic.actions.loadJourneys()

        await expectLogic(logic)
            .toDispatchActions(['loadActiveInsight', 'loadActiveInsightSuccess'])
            .toNotHaveDispatchedActions(['loadActiveInsightFailure'])
            .toMatchValues({ activeInsight: null })
    })
})
