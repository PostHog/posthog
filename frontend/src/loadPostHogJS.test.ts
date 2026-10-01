import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { LastSeenFeatureFlags, isInDeferredInitSample, loadPostHogJS, withLastSeenFeatureFlags } from './loadPostHogJS'

describe('loadPostHogJS', () => {
    describe('withLastSeenFeatureFlags', () => {
        const serverFlags = { 'server-decided': false, variant: 'control' }

        it.each<{
            case: string
            lastSeen: LastSeenFeatureFlags | null
            bootstrapFlags: LastSeenFeatureFlags['featureFlags']
            expected: LastSeenFeatureFlags['featureFlags']
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
})
