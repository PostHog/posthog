import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { AppContext } from '~/types'

import { isInDeferredInitSample, loadPostHogJS } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
        'keeps the posthog-js sampling verdict for session %p',
        (sessionId) => {
            expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
        }
    )

    it.each([
        ['hobby', { run_mode: 'HOBBY' }, false],
        ['US cloud', { run_mode: 'US' }, undefined],
        ['EU cloud', { run_mode: 'EU' }, undefined],
        ['cloud development', { run_mode: 'DEV' }, undefined],
        ['local development', { run_mode: 'LOCAL' }, undefined],
        ['E2E', { run_mode: 'E2E' }, undefined],
        ['older app context', {}, undefined],
        ['missing app context', undefined, undefined],
    ] as const)('selects script versioning for %s', (_, context, expected) => {
        const original = {
            key: window.JS_POSTHOG_API_KEY,
            host: window.JS_POSTHOG_HOST,
            context: window.POSTHOG_APP_CONTEXT,
        }
        window.JS_POSTHOG_API_KEY = 'phc_example'
        window.JS_POSTHOG_HOST = window.location.origin
        window.POSTHOG_APP_CONTEXT = context as AppContext | undefined
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
            window.POSTHOG_APP_CONTEXT = original.context
        }
    })
})
