import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { ActivityScope } from '~/types'

import { makeTestSetup } from './activityLogLogic.test.setup'

describe('the activity log logic', () => {
    describe('humanizing experiments', () => {
        // Guards the routing: a single experiment's activity must come from the experiment's
        // own /activity endpoint (which merges holdout and shared-metric entries), not the
        // generic /activity_log endpoint. If routing regresses, this mock is never hit and
        // the log renders empty.
        const experimentTestSetup = makeTestSetup(
            ActivityScope.EXPERIMENT,
            `/api/projects/${MOCK_TEAM_ID}/experiments/7/activity/`
        )

        it('fetches from the experiment activity endpoint and humanizes a launch', async () => {
            const logic = await experimentTestSetup('my experiment', 'updated', [
                {
                    type: ActivityScope.EXPERIMENT,
                    action: 'created',
                    field: 'start_date',
                    before: null,
                    after: '2024-01-01T00:00:00Z',
                },
            ])

            const actual = logic.values.humanizedActivity
            const text = render(<>{actual[0].description}</>).container.textContent
            expect(text).toContain('peter')
            expect(text).toContain('launched experiment')
            expect(text).toContain('my experiment')
        })
    })
})
