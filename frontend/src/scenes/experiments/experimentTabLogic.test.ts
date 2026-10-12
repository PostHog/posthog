import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { experimentTabLogic } from './experimentTabLogic'

const EXPERIMENTS_URL = '/api/projects/:team_id/experiments/'

describe('experimentTabLogic', () => {
    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
    })

    it('flags a failed load, captures it once, and clears the flag when a retry succeeds', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        try {
            useMocks({ get: { [EXPERIMENTS_URL]: () => [500, { detail: 'boom' }] } })
            const logic = experimentTabLogic({ featureFlagId: 1 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadRelatedExperimentsFailure'])
            await expectLogic(logic, () => logic.actions.loadRelatedExperiments()).toDispatchActions([
                'loadRelatedExperimentsFailure',
            ])

            expect(logic.values.relatedExperimentsLoadFailed).toBe(true)
            expect(
                capture.mock.calls.filter(([event]) => event === 'feature flag experiments tab load failed')
            ).toEqual([['feature flag experiments tab load failed', { status: 500 }]])

            useMocks({ get: { [EXPERIMENTS_URL]: () => [200, { results: [] }] } })
            await expectLogic(logic, () => logic.actions.loadRelatedExperiments()).toDispatchActions([
                'loadRelatedExperimentsSuccess',
            ])

            expect(logic.values.relatedExperimentsLoadFailed).toBe(false)
        } finally {
            capture.mockRestore()
        }
    })
})
