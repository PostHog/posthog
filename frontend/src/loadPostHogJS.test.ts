import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { AppContext } from '~/types'

import { LastSeenFeatureFlags, isInDeferredInitSample, loadPostHogJS, withLastSeenFeatureFlags } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    describe('withLastSeenFeatureFlags', () => {
        const serverFlags = { 'server-decided': false, variant: 'control' }

        it.each<{
            case: string
            lastSeen: LastSeenFeatureFlags | null
            bootstrapFlags: LastSeenFeatureFlags['featureFlags'] | null | undefined
            expected: LastSeenFeatureFlags['featureFlags'] | undefined
        }>([
            {
                case: 'fills flags the server left out, and server values win',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'server-decided': true, 'staff-only': true } },
                bootstrapFlags: serverFlags,
                expected: { 'server-decided': false, variant: 'control', 'staff-only': true },
            },
            {
                case: 'ignores flags another user saw on this browser',
                lastSeen: { distinctId: 'user-b', featureFlags: { 'staff-only': true } },
                bootstrapFlags: serverFlags,
                expected: serverFlags,
            },
            {
                case: 'keeps an empty bootstrap empty so posthog-js uses its own persisted flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: {},
                expected: {},
            },
            {
                case: 'keeps missing bootstrap flags absent when the same user has cached flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: undefined,
                expected: undefined,
            },
            {
                case: 'ignores null bootstrap flags when the same user has cached flags',
                lastSeen: { distinctId: 'user-a', featureFlags: { 'staff-only': true } },
                bootstrapFlags: null,
                expected: undefined,
            },
            {
                case: 'keeps the server flags when nothing is cached',
                lastSeen: null,
                bootstrapFlags: serverFlags,
                expected: serverFlags,
            },
        ])('$case', ({ lastSeen, bootstrapFlags, expected }) => {
            expect(withLastSeenFeatureFlags({ featureFlags: bootstrapFlags }, lastSeen, 'user-a').featureFlags).toEqual(
                expected
            )
        })
    })

    describe('isInDeferredInitSample', () => {
        it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
            'keeps the posthog-js sampling verdict for session %p',
            (sessionId) => {
                expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
            }
        )
    })

    describe('without a project key', () => {
        it('starts posthog-js with no request to PostHog', () => {
            window.JS_POSTHOG_API_KEY = undefined

            loadPostHogJS()

            expect(posthog.init).toHaveBeenCalledWith(
                'fake_token',
                expect.objectContaining({ advanced_disable_flags: true, opt_out_capturing_by_default: true })
            )
        })
    })

    it.each([
        ['hobby with self-capture', { run_mode: 'HOBBY' }, true, false],
        ['hobby with Cloud assets', { run_mode: 'HOBBY' }, false, undefined],
        ['US cloud', { run_mode: 'US' }, false, undefined],
        ['EU cloud', { run_mode: 'EU' }, false, undefined],
        ['cloud development', { run_mode: 'DEV' }, false, undefined],
        ['local development', { run_mode: 'LOCAL' }, false, undefined],
        ['E2E', { run_mode: 'E2E' }, false, undefined],
        ['older app context', {}, false, undefined],
        ['missing app context', undefined, false, undefined],
    ] as const)('selects script versioning for %s', (_, context, selfCapture, expected) => {
        const original = {
            key: window.JS_POSTHOG_API_KEY,
            host: window.JS_POSTHOG_HOST,
            selfCapture: window.JS_POSTHOG_SELF_CAPTURE,
            context: window.POSTHOG_APP_CONTEXT,
        }
        window.JS_POSTHOG_API_KEY = 'phc_example'
        window.JS_POSTHOG_HOST = window.location.origin
        window.JS_POSTHOG_SELF_CAPTURE = selfCapture
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
            window.JS_POSTHOG_SELF_CAPTURE = original.selfCapture
            window.POSTHOG_APP_CONTEXT = original.context
        }
    })
})
