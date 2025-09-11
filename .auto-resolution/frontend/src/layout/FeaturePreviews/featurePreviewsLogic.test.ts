import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featurePreviewsLogic } from './featurePreviewsLogic'

// Mock posthog-js
jest.mock('posthog-js')

// Set up the mock methods that various parts of the code need
const mockedPosthog = posthog as jest.Mocked<typeof posthog>
mockedPosthog.get_session_replay_url = jest.fn(() => 'http://localhost/replay/123')

describe('featurePreviewsLogic - submitEarlyAccessFeatureFeedback', () => {
    let logic: ReturnType<typeof featurePreviewsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()

        useMocks({
            post: {
                'https://posthoghelp.zendesk.com/api/v2/requests.json': [200, {}],
            },
        })
        initKeaTests()
        logic = featurePreviewsLogic()
        logic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
    })

    test('submitting feedback', async () => {
        logic.actions.beginEarlyAccessFeatureFeedback('test')
        const promise = logic.asyncActions.submitEarlyAccessFeatureFeedback('test')
        await expectLogic(logic)
            .toMatchValues({ activeFeedbackFlagKeyLoading: true })
            .toDispatchActions(['submitEarlyAccessFeatureFeedback'])
            .toNotHaveDispatchedActions(['submitEarlyAccessFeatureFeedbackSuccess'])
        await promise
        await expectLogic(logic)
            .toMatchValues({ activeFeedbackFlagKeyLoading: false })
            .toDispatchActions(['submitEarlyAccessFeatureFeedbackSuccess'])
    })
})

describe('featurePreviewsLogic - updateEarlyAccessFeatureEnrollment', () => {
    let logic: ReturnType<typeof featurePreviewsLogic.build>
    const mockUpdateEnrollment = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()

        // Set up the mock implementation for posthog
        ;(posthog as any).updateEarlyAccessFeatureEnrollment = mockUpdateEnrollment

        useMocks({
            post: {
                'https://posthoghelp.zendesk.com/api/v2/requests.json': [200, {}],
            },
        })
        initKeaTests()
        logic = featurePreviewsLogic()
        logic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
    })

    test('updating early access feature enrollment without stage', () => {
        logic.actions.updateEarlyAccessFeatureEnrollment('test-flag', true)

        expect(mockUpdateEnrollment).toHaveBeenCalledWith('test-flag', true, undefined)
    })

    test('updating early access feature enrollment with stage', () => {
        logic.actions.updateEarlyAccessFeatureEnrollment('test-flag', true, 'beta')

        expect(mockUpdateEnrollment).toHaveBeenCalledWith('test-flag', true, 'beta')
    })

    test('updating early access feature enrollment with different stages', () => {
        // Test concept stage
        logic.actions.updateEarlyAccessFeatureEnrollment('concept-flag', false, 'concept')
        expect(mockUpdateEnrollment).toHaveBeenCalledWith('concept-flag', false, 'concept')

        // Test alpha stage
        logic.actions.updateEarlyAccessFeatureEnrollment('alpha-flag', true, 'alpha')
        expect(mockUpdateEnrollment).toHaveBeenCalledWith('alpha-flag', true, 'alpha')
    })
})
