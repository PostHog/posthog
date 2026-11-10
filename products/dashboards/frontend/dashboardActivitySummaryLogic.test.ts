import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dashboardActivitySummaryLogic } from './dashboardActivitySummaryLogic'

describe('dashboardActivitySummaryLogic', () => {
    let requests = 0

    beforeEach(() => {
        requests = 0
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                '/api/projects/:team_id/dashboards/:id/activity_summary/': () => {
                    requests += 1
                    return [404, { detail: 'Endpoint not found.' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(resumeKeaLoadersErrors)

    it('does not load again when the hover opens after a failed load', async () => {
        const logic = dashboardActivitySummaryLogic({ dashboardId: 7 })
        logic.mount()

        await expectLogic(logic, () => logic.actions.openActivitySummary())
            .toDispatchActions(['loadActivitySummary', 'loadActivitySummaryFailure'])
            .toMatchValues({ activitySummary: null, activitySummaryFailed: true })

        logic.actions.openActivitySummary()
        logic.actions.openActivitySummary()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toBe(1)
    })
})
