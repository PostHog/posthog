import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CustomerJourneyApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerJourneysLogic } from './customerJourneysLogic'

const JOURNEYS_URL = '/api/environments/:team_id/customer_journeys/'
const INSIGHT_URL = '/api/environments/:team_id/insights/:id'

const journey: CustomerJourneyApi = {
    id: 'journey-1',
    insight: 42,
    name: 'Onboarding',
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: 1,
    updated_at: null,
}

describe('customerJourneysLogic', () => {
    let logic: ReturnType<typeof customerJourneysLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    // A journey can point at a soft-deleted insight (the FK cascade does not fire), so the insight
    // endpoint 404s. That must degrade into a missing insight, not fall through to the global error
    // toast. A genuine server error still has to surface as a failure.
    it('treats a deleted journey insight (404) as a missing insight, not an app-level failure', async () => {
        useMocks({
            get: {
                [JOURNEYS_URL]: { results: [journey] },
                [INSIGHT_URL]: () => [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
        logic = customerJourneysLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadJourneys()
        })
            .toDispatchActions(['loadActiveInsightSuccess'])
            .toNotHaveDispatchedActions(['loadActiveInsightFailure'])
            .toMatchValues({ activeInsight: null })
    })

    it('still surfaces a non-404 insight error as a failure', async () => {
        useMocks({
            get: {
                [JOURNEYS_URL]: { results: [journey] },
                [INSIGHT_URL]: () => [500, { detail: 'Server error.' }],
            },
        })
        initKeaTests()
        logic = customerJourneysLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadJourneys()
        }).toDispatchActions(['loadActiveInsightFailure'])
    })
})
