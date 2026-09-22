import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { isInDeferredInitSample, loadPostHogJS } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
        'keeps the posthog-js sampling verdict for session %p',
        (sessionId) => {
            expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
        }
    )

    it.each([
        ['self-capture on this instance', true, window.location.origin, false],
        ['self-capture using a CDN', true, 'https://cdn.example.com', undefined],
        ['cloud capture', false, 'https://cdn.example.com', undefined],
        ['same-origin without self-capture', false, window.location.origin, undefined],
    ] as const)('selects script versioning for %s', (_, selfCapture, host, expected) => {
        const original = {
            key: window.JS_POSTHOG_API_KEY,
            host: window.JS_POSTHOG_HOST,
            selfCapture: window.JS_POSTHOG_SELF_CAPTURE,
        }
        window.JS_POSTHOG_API_KEY = 'phc_example'
        window.JS_POSTHOG_HOST = host
        window.JS_POSTHOG_SELF_CAPTURE = selfCapture
        jest.mocked(posthog.get_session_id).mockReturnValue('example-session')
        jest.mocked(posthog.init).mockClear()
        try {
            loadPostHogJS()
            const config = jest.mocked(posthog.init).mock.calls[0][1]
            if (expected === undefined) {
                expect(config).not.toHaveProperty('strict_script_versioning')
            } else {
                expect(config).toHaveProperty('strict_script_versioning', expected)
            }
        } finally {
            window.JS_POSTHOG_API_KEY = original.key
            window.JS_POSTHOG_HOST = original.host
            window.JS_POSTHOG_SELF_CAPTURE = original.selfCapture
        }
    })
})
