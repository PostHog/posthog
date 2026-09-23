import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { describeFeatureFlagsFailure, isInDeferredInitSample, loadPostHogJS } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    describe('isInDeferredInitSample', () => {
        it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
            'keeps the posthog-js sampling verdict for session %p',
            (sessionId) => {
                expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
            }
        )
    })

    describe('describeFeatureFlagsFailure', () => {
        it.each([
            [
                'an HTTP error',
                ['api_error_503'],
                {
                    $feature_flag_error: 'api_error_503',
                    feature_flag_error_status: 503,
                    feature_flag_response_received: true,
                },
            ],
            [
                'a timeout',
                ['timeout'],
                {
                    $feature_flag_error: 'timeout',
                    feature_flag_error_status: null,
                    feature_flag_response_received: false,
                },
            ],
            [
                'a blocked request',
                ['connection_error'],
                {
                    $feature_flag_error: 'connection_error',
                    feature_flag_error_status: null,
                    feature_flag_response_received: false,
                },
            ],
            [
                'an unclassified transport failure',
                ['unknown_error'],
                {
                    $feature_flag_error: 'unknown_error',
                    feature_flag_error_status: null,
                    feature_flag_response_received: false,
                },
            ],
            [
                'an api error with no status',
                ['api_error_'],
                {
                    $feature_flag_error: 'api_error_',
                    feature_flag_error_status: null,
                    feature_flag_response_received: true,
                },
            ],
            [
                'several codes',
                ['api_error_500', 'errors_while_computing_flags'],
                {
                    $feature_flag_error: 'api_error_500,errors_while_computing_flags',
                    feature_flag_error_status: 500,
                    feature_flag_response_received: true,
                },
            ],
            [
                'no persisted codes',
                undefined,
                {
                    $feature_flag_error: 'unknown_error',
                    feature_flag_error_status: null,
                    feature_flag_response_received: false,
                },
            ],
        ])('describes %s', (_name, sdkErrors, expected) => {
            expect(describeFeatureFlagsFailure(sdkErrors)).toEqual(expected)
        })
    })

    describe('without a project key', () => {
        it('starts posthog-js with no request to PostHog', () => {
            window.JS_POSTHOG_API_KEY = undefined

            loadPostHogJS()

            expect(posthog.init).toHaveBeenCalledWith(
                'fake_token',
                expect.objectContaining({ advanced_disable_flags: true })
            )
        })
    })
})
