import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { todayPromptsLogic } from './todayPromptsLogic'

describe('todayPromptsLogic', () => {
    beforeEach(() => {
        localStorage.clear()
    })

    test.each([
        { name: 'the flag is off', flagOn: false, aiApproved: true, dismissed: false, expected: false },
        { name: 'PostHog AI is off', flagOn: true, aiApproved: false, dismissed: false, expected: false },
        { name: 'the prompt was dismissed', flagOn: true, aiApproved: true, dismissed: true, expected: false },
        { name: 'nothing blocks it', flagOn: true, aiApproved: true, dismissed: false, expected: true },
    ])('offers self-driving only when allowed: $name', ({ flagOn, aiApproved, dismissed, expected }) => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: aiApproved,
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            flagOn ? [FEATURE_FLAGS.PRODUCT_AUTONOMY] : [],
            flagOn ? { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true } : {}
        )
        const logic = todayPromptsLogic()
        logic.mount()

        if (dismissed) {
            logic.actions.dismissPrompt('self_driving')
        }

        expect(logic.values.canOfferSelfDriving).toBe(expected)
    })
})
