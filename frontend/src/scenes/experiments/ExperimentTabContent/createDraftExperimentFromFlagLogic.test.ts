import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { createDraftExperimentFromFlagLogic } from './createDraftExperimentFromFlagLogic'

describe('createDraftExperimentFromFlagLogic', () => {
    let logic: ReturnType<typeof createDraftExperimentFromFlagLogic.build>
    let capturedPayload: Record<string, any> | null

    beforeEach(() => {
        capturedPayload = null
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/experiments`]: async ({ request }) => {
                    capturedPayload = (await request.json()) as Record<string, any>
                    return [200, { id: 7, name: capturedPayload.name }]
                },
            },
        })
        initKeaTests()
        logic = createDraftExperimentFromFlagLogic({ featureFlagKey: 'flag-with-rules' })
        logic.mount()
        logic.actions.setExperimentName('Checkout test')
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['a flag with rules', 'rule-b', ['rule-b']],
        ['any other flag', null, []],
    ])('creates the draft on %s', async (_, ruleId, expectedRuleIds) => {
        logic.actions.createDraftExperiment(ruleId)

        await waitFor(() => expect(capturedPayload).not.toBeNull())
        expect(capturedPayload).toMatchObject({ name: 'Checkout test', feature_flag_key: 'flag-with-rules' })
        expect(Object.keys(capturedPayload ?? {}).includes('feature_flag_rule_id')).toBe(expectedRuleIds.length > 0)
        expect(capturedPayload?.feature_flag_rule_id).toEqual(expectedRuleIds[0])
    })
})
