import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog, { BeforeSendFn } from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { FEATURE_FLAGS } from 'lib/constants'
import { isOAuthMode } from 'lib/oauth/oauthClient'

import { AppContext } from '~/types'

import {
    filterLcpDiagnostics,
    isInDeferredInitSample,
    loadPostHogJS,
    shouldCaptureLcpDiagnostics,
} from './loadPostHogJS'

jest.mock('lib/oauth/oauthClient', () => ({ isOAuthMode: jest.fn(() => false) }))

describe('loadPostHogJS', () => {
    it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
        'keeps the posthog-js sampling verdict for session %p',
        (sessionId) => {
            expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
        }
    )

    describe('LCP diagnostics', () => {
        const originalLocation = window.location
        const originalIdentity = window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        const originalContext = window.POSTHOG_APP_CONTEXT
        const originalImpersonation = window.IMPERSONATED_SESSION
        const originalApiKey = window.JS_POSTHOG_API_KEY

        afterEach(() => {
            Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = originalIdentity
            window.POSTHOG_APP_CONTEXT = originalContext
            window.IMPERSONATED_SESSION = originalImpersonation
            window.JS_POSTHOG_API_KEY = originalApiKey
            jest.restoreAllMocks()
            jest.mocked(isOAuthMode).mockReturnValue(false)
        })

        it.each([
            ['us.posthog.com', '/project/123/web', true, true, false, false, true],
            ['us.posthog.com', '/project/123/web/', true, true, false, false, true],
            ['eu.posthog.com', '/project/123/web', true, true, false, false, false],
            ['us.posthog.com', '/project/123/sql', true, true, false, false, false],
            ['us.posthog.com', '/project/123/web', false, true, false, false, false],
            ['us.posthog.com', '/project/123/web', 'test', true, false, false, false],
            ['us.posthog.com', '/project/123/web', true, false, false, false, false],
            ['us.posthog.com', '/project/123/web', true, true, true, false, false],
            ['us.posthog.com', '/project/123/web', true, true, false, true, false],
        ])(
            'limits the pilot: %s %s %s %s %s %s',
            (hostname, pathname, flag, identified, impersonated, oauth, expected) => {
                Object.defineProperty(window, 'location', { configurable: true, value: { hostname, pathname } })
                window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
                    featureFlags: { [FEATURE_FLAGS.WEB_LCP_DIAGNOSTICS]: flag },
                }
                window.IMPERSONATED_SESSION = impersonated
                window.POSTHOG_APP_CONTEXT = {
                    current_user: identified ? MOCK_DEFAULT_USER : null,
                } as AppContext
                jest.mocked(isOAuthMode).mockReturnValue(oauth)
                expect(shouldCaptureLcpDiagnostics()).toBe(expected)
                delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
                expect(shouldCaptureLcpDiagnostics()).toBe(false)
            }
        )

        it.each([true, false])('preserves caller event filters with the pilot set to %s', (enabled) => {
            Object.defineProperty(window, 'location', {
                configurable: true,
                value: { hostname: 'us.posthog.com', pathname: '/project/123/web' },
            })
            window.JS_POSTHOG_API_KEY = 'test-token'
            window.IMPERSONATED_SESSION = false
            window.POSTHOG_APP_CONTEXT = { current_user: MOCK_DEFAULT_USER } as AppContext
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
                featureFlags: { [FEATURE_FLAGS.WEB_LCP_DIAGNOSTICS]: enabled },
            }
            const init = jest.spyOn(posthog, 'init').mockReturnValue(posthog)
            jest.spyOn(posthog, 'get_session_id').mockReturnValue('test-session')
            jest.spyOn(posthog, 'onFeatureFlags').mockReturnValue(() => {})
            const callerFilter: BeforeSendFn = () => null

            loadPostHogJS({ beforeSend: [callerFilter] })

            const config = init.mock.calls[0][1]!
            expect(config.capture_performance).toEqual({ web_vitals_attribution: enabled ? ['LCP'] : false })
            expect(config.before_send).toEqual(enabled ? [filterLcpDiagnostics, callerFilter] : [callerFilter])
        })

        it('keeps only finite LCP phase timings and preserves the measured LCP value', () => {
            const event = {
                uuid: '01234567-89ab-4def-8123-456789abcdef',
                event: '$web_vitals',
                properties: {
                    $web_vitals_LCP_value: 2400,
                    $web_vitals_LCP_event: {
                        attribution: {
                            timeToFirstByte: 100,
                            resourceLoadDelay: 0,
                            resourceLoadDuration: Infinity,
                            elementRenderDelay: -1,
                            target: '#customer-name',
                            url: 'https://example.com/private?token=test',
                            futureField: 'private',
                        },
                    },
                },
            }
            expect(filterLcpDiagnostics(event)).toEqual({
                ...event,
                properties: {
                    $web_vitals_LCP_value: 2400,
                    $web_vitals_LCP_event: { attribution: { timeToFirstByte: 100, resourceLoadDelay: 0 } },
                    lcp_diagnostics: true,
                    lcp_navigation_start: performance.timeOrigin,
                },
            })
            expect(filterLcpDiagnostics(null)).toBeNull()
        })
    })
})
