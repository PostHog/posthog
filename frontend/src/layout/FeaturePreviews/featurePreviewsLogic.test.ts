import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featurePreviewsLogic } from './featurePreviewsLogic'

// Mock posthog-js
jest.mock('posthog-js')
// Mock lemonToast
jest.mock('lib/lemon-ui/LemonToast')

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

describe('featurePreviewsLogic - updateEarlyAccessFeatureEnrollment (impersonated session)', () => {
    let logic: ReturnType<typeof featurePreviewsLogic.build>
    const mockUpdateEnrollment = jest.fn()
    let originalImpersonatedSession: boolean | undefined

    beforeEach(() => {
        jest.clearAllMocks()

        // Mock window.IMPERSONATED_SESSION
        originalImpersonatedSession = window.IMPERSONATED_SESSION
        window.IMPERSONATED_SESSION = true

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

    afterEach(() => {
        window.IMPERSONATED_SESSION = originalImpersonatedSession
        jest.restoreAllMocks()
    })

    test('shows error toast when trying to update enrollment while impersonating', () => {
        logic.actions.updateEarlyAccessFeatureEnrollment('test-flag', true)

        expect(mockUpdateEnrollment).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith(
            'Cannot update early access feature enrollment while impersonating a user'
        )
    })

    test('shows error toast for all update attempts during impersonation', () => {
        logic.actions.updateEarlyAccessFeatureEnrollment('test-flag', false)
        logic.actions.updateEarlyAccessFeatureEnrollment('beta-flag', true, 'beta')

        expect(mockUpdateEnrollment).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledTimes(2)
        expect(lemonToast.error).toHaveBeenCalledWith(
            'Cannot update early access feature enrollment while impersonating a user'
        )
    })
})
