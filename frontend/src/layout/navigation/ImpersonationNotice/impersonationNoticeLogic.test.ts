import {
    MOCK_DEFAULT_BASIC_USER,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_USER,
} from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationMemberType, Region, UserType } from '~/types'

import { impersonationNoticeLogic } from './impersonationNoticeLogic'

jest.mock('@posthog/lemon-ui', () => {
    const actual = jest.requireActual('@posthog/lemon-ui')
    return {
        ...actual,
        lemonToast: {
            ...actual.lemonToast,
            success: jest.fn(),
            error: jest.fn(),
            info: jest.fn(),
        },
    }
})

const MOCK_IMPERSONATED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_impersonated: true,
    is_impersonated_read_only: true,
    is_impersonated_until: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
    },
}

function mockMember(
    firstName: string,
    level: OrganizationMembershipLevel,
    id: number,
    uuid: string
): OrganizationMemberType {
    return {
        ...MOCK_DEFAULT_ORGANIZATION_MEMBER,
        id: `member-${id}`,
        user: {
            ...MOCK_DEFAULT_BASIC_USER,
            id,
            uuid,
            first_name: firstName,
            last_name: '',
            distinct_id: `distinct-${id}`,
            email: `${firstName.toLowerCase()}@example.com`,
        },
        level,
    }
}

describe('impersonationNoticeLogic', () => {
    let logic: ReturnType<typeof impersonationNoticeLogic.build>

    beforeEach(() => {
        // returnToTicketContext is a persisted reducer; clear storage so a value set
        // in one test doesn't leak into the next.
        localStorage.clear()
        useMocks({
            get: {
                '/api/users/@me/': () => [200, MOCK_DEFAULT_USER],
                '/admin/auth_check': () => [200, {}],
                '/api/organizations/:org/members/': () => [200, { results: [], count: 0 }],
            },
            post: {
                '/admin/login/user/:id/': () => [200, {}],
            },
        })
        initKeaTests()
        userLogic.mount()
        membersLogic.mount()
        logic = impersonationNoticeLogic()
        logic.mount()
    })

    describe('reducers', () => {
        it('sets expiredSessionInfo via setSessionExpired', async () => {
            const info = { email: 'test@example.com', userId: 123, isImpersonatedUntil: null }

            await expectLogic(logic, () => {
                logic.actions.setSessionExpired(info)
            }).toMatchValues({
                expiredSessionInfo: info,
                isSessionExpired: true,
            })
        })

        it('clears expiredSessionInfo when set to null', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            await expectLogic(logic, () => {
                logic.actions.setSessionExpired(null)
            }).toMatchValues({
                expiredSessionInfo: null,
                isSessionExpired: false,
            })
        })

        it('sets isReImpersonating to true on reImpersonate', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            await expectLogic(logic, () => {
                logic.actions.reImpersonate('support ticket #123', true)
            }).toMatchValues({
                isReImpersonating: true,
            })
        })

        it('resets isReImpersonating on reImpersonateFailure', async () => {
            await expectLogic(logic, () => {
                logic.actions.reImpersonateFailure('some error')
            }).toMatchValues({
                isReImpersonating: false,
            })
        })

        it('resets isReImpersonating when session expired state changes', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })
            logic.actions.reImpersonate('reason', true)

            await expectLogic(logic, () => {
                logic.actions.setSessionExpired(null)
            }).toMatchValues({
                isReImpersonating: false,
            })
        })
    })

    describe('selectors', () => {
        it('isReadOnly defaults to true when user is not impersonated', async () => {
            await expectLogic(logic).toMatchValues({
                isReadOnly: true,
            })
        })

        it('isImpersonated reflects user state', async () => {
            await expectLogic(logic).toMatchValues({
                isImpersonated: false,
            })

            useMocks({
                get: {
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
            })
            userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)

            await expectLogic(logic).toMatchValues({
                isImpersonated: true,
                isReadOnly: true,
            })
        })
    })

    describe('initiateImpersonation listener', () => {
        const TICKET_ID = 'b6d0f1e2-0000-4000-8000-000000000000'

        it('opens the other region admin and clears loading when the ticket is cross-region', async () => {
            logic.actions.setTicketContext({ ticketId: TICKET_ID, email: 'a@example.com', region: Region.EU })
            useMocks({
                get: { '/admin/auth_check': () => [200, {}] },
                post: {
                    '/admin/impersonation/from-ticket/': () => [
                        200,
                        { redirect_region: 'EU', redirect_url: 'https://eu.posthog.com/admin/posthog/user/?q=a' },
                    ],
                },
            })
            const openSpy = jest.spyOn(window, 'open').mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.initiateImpersonation()
            })
                .toFinishAllListeners()
                .toMatchValues({ isInitiatingImpersonation: false })

            expect(openSpy).toHaveBeenCalledWith('https://eu.posthog.com/admin/posthog/user/?q=a', '_blank')
            expect(lemonToast.info).toHaveBeenCalled()
            openSpy.mockRestore()
        })

        it('shows an error toast and clears loading when the endpoint fails', async () => {
            logic.actions.setTicketContext({ ticketId: TICKET_ID, email: 'a@example.com', region: Region.US })
            useMocks({
                get: { '/admin/auth_check': () => [200, {}] },
                post: {
                    '/admin/impersonation/from-ticket/': () => [404, { error: 'No user found for this email' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.initiateImpersonation()
            })
                .toFinishAllListeners()
                .toMatchValues({ isInitiatingImpersonation: false })

            expect(lemonToast.error).toHaveBeenCalledWith('No user found for this email')
        })

        it('does nothing without a ticket context', async () => {
            await expectLogic(logic, () => {
                logic.actions.initiateImpersonation()
            })
                .toFinishAllListeners()
                .toMatchValues({ isInitiatingImpersonation: false })

            expect(lemonToast.error).not.toHaveBeenCalled()
        })

        it('persists the return-to-ticket context on the same-region success path', async () => {
            logic.actions.setTicketContext({
                ticketId: TICKET_ID,
                ticketNumber: 42,
                email: 'a@example.com',
                region: Region.US,
            })
            useMocks({
                get: { '/admin/auth_check': () => [200, {}] },
                post: {
                    '/admin/impersonation/from-ticket/': () => [200, { success: true, ticket_id: TICKET_ID }],
                },
            })
            const originalLocation = window.location
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: { ...originalLocation, replace: jest.fn() },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.initiateImpersonation()
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        returnToTicketContext: { ticketNumber: 42, email: 'a@example.com' },
                    })

                expect(window.location.replace).toHaveBeenCalledWith('/')
            } finally {
                Object.defineProperty(window, 'location', {
                    configurable: true,
                    writable: true,
                    value: originalLocation,
                })
            }
        })
    })

    describe('returnToTicket listener', () => {
        it('logs out of impersonation back to the ticket and shows a loading state', async () => {
            logic.actions.setReturnToTicketContext({ ticketNumber: 42, email: 'a@example.com' })

            const originalLocation = window.location
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: { ...originalLocation, href: originalLocation.href },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.returnToTicket()
                })
                    .toFinishAllListeners()
                    // Context is intentionally kept so the button doesn't flip variants
                    // before navigating; isReturningToTicket drives the loading state.
                    .toMatchValues({
                        returnToTicketContext: { ticketNumber: 42, email: 'a@example.com' },
                        isReturningToTicket: true,
                    })

                expect(window.location.href).toBe('/admin/logout/?next=%2Fsupport%2Ftickets%2F42')
            } finally {
                Object.defineProperty(window, 'location', {
                    configurable: true,
                    writable: true,
                    value: originalLocation,
                })
            }
        })

        it('does nothing when there is no stored ticket context', async () => {
            const originalLocation = window.location
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: { ...originalLocation, href: 'sentinel' },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.returnToTicket()
                }).toFinishAllListeners()

                expect(window.location.href).toBe('sentinel')
            } finally {
                Object.defineProperty(window, 'location', {
                    configurable: true,
                    writable: true,
                    value: originalLocation,
                })
            }
        })
    })

    describe('canReturnToTicket selector', () => {
        const matchingEmail = MOCK_IMPERSONATED_USER.email

        it.each([
            { name: 'no stored context', context: null as any, user: MOCK_IMPERSONATED_USER, expected: false },
            {
                name: 'not impersonated',
                context: { ticketNumber: 42, email: matchingEmail },
                user: MOCK_DEFAULT_USER,
                expected: false,
            },
            {
                name: 'impersonating a different email',
                context: { ticketNumber: 42, email: 'someone-else@example.com' },
                user: MOCK_IMPERSONATED_USER,
                expected: false,
            },
            {
                name: 'impersonating the stored email',
                context: { ticketNumber: 42, email: matchingEmail },
                user: MOCK_IMPERSONATED_USER,
                expected: true,
            },
        ])('is $expected when $name', async ({ context, user, expected }) => {
            userLogic.actions.loadUserSuccess(user)
            if (context) {
                logic.actions.setReturnToTicketContext(context)
            }

            await expectLogic(logic).toMatchValues({ canReturnToTicket: expected })
        })
    })

    describe('expiredSessionFromTicket selector', () => {
        it.each([
            {
                name: 'no expired session',
                expired: null as any,
                context: { ticketNumber: 42, email: 'a@x.com' },
                expected: false,
            },
            {
                name: 'no stored context',
                expired: { email: 'a@x.com', userId: 1, isImpersonatedUntil: null },
                context: null as any,
                expected: false,
            },
            {
                name: 'emails differ',
                expired: { email: 'a@x.com', userId: 1, isImpersonatedUntil: null },
                context: { ticketNumber: 42, email: 'b@x.com' },
                expected: false,
            },
            {
                name: 'emails match',
                expired: { email: 'a@x.com', userId: 1, isImpersonatedUntil: null },
                context: { ticketNumber: 42, email: 'a@x.com' },
                expected: true,
            },
        ])('is $expected when $name', async ({ expired, context, expected }) => {
            if (expired) {
                logic.actions.setSessionExpired(expired)
            }
            if (context) {
                logic.actions.setReturnToTicketContext(context)
            }

            await expectLogic(logic).toMatchValues({ expiredSessionFromTicket: expected })
        })
    })

    describe('reImpersonate listener', () => {
        it('calls login-as endpoint and dispatches loadUser on success', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                    '/admin/auth_check': () => [200, {}],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.reImpersonate('support ticket #123', true)
            })
                .toDispatchActions(['reImpersonate', 'loadUser'])
                .toFinishAllListeners()
        })

        it('does nothing when expiredSessionInfo is null', async () => {
            await expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })
                .toNotHaveDispatchedActions(['loadUser'])
                .toFinishAllListeners()
        })

        it('shows error toast and dispatches reImpersonateFailure on login failure', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/admin/auth_check': () => [200, {}],
                },
                post: {
                    '/admin/login/user/:id/': () => [403, { detail: 'Forbidden' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    isReImpersonating: false,
                })

            expect(lemonToast.error).toHaveBeenCalled()
        })

        it('shows error toast when OAuth2 popup is blocked', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/admin/auth_check': () => [401, {}],
                },
            })

            const openSpy = jest.spyOn(window, 'open').mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })
                .toFinishAllListeners()
                .toDispatchActions(['reImpersonateFailure'])
                .toMatchValues({
                    isReImpersonating: false,
                })

            expect(lemonToast.error).toHaveBeenCalledWith(
                'Popup blocked. Please allow popups for this site and try again.'
            )
            openSpy.mockRestore()
        })

        it('opens OAuth2 popup when auth check fails and proceeds once the popup confirms success', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/admin/auth_check': () => [401, {}],
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            const mockWindow = { closed: false } as Window
            const openSpy = jest.spyOn(window, 'open').mockReturnValue(mockWindow)

            const reImpersonatePromise = expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })

            // The popup signals a successful admin OAuth2 grant — only then may the flow proceed
            await new Promise((resolve) => setTimeout(resolve, 100))
            window.dispatchEvent(
                new MessageEvent('message', {
                    origin: window.location.origin,
                    data: { type: 'oauth2_complete' },
                })
            )

            await reImpersonatePromise.toDispatchActions(['reImpersonate', 'loadUser']).toFinishAllListeners()

            expect(openSpy).toHaveBeenCalledWith(
                '/admin/oauth2/success',
                'admin_oauth2',
                expect.stringContaining('width=600')
            )
            openSpy.mockRestore()
        })

        it('fails without impersonating when the OAuth2 popup closes before confirming', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/admin/auth_check': () => [401, {}],
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            const mockWindow = { closed: false } as Window
            const openSpy = jest.spyOn(window, 'open').mockReturnValue(mockWindow)

            const reImpersonatePromise = expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })

            // Popup closes without ever posting `oauth2_complete` — the admin session was never
            // established, so the flow must surface a failure rather than fire the login-as POST.
            await new Promise((resolve) => setTimeout(resolve, 100))
            ;(mockWindow as any).closed = true

            await reImpersonatePromise
                .toDispatchActions(['reImpersonate', 'reImpersonateFailure'])
                .toNotHaveDispatchedActions(['loadUser'])
                .toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalled()
            openSpy.mockRestore()
        })
    })

    describe('returnToPostHog listener', () => {
        it('navigates to the loginas logout endpoint with next pointing back to the app', async () => {
            // Drain mount-time requests first: while window.location.href holds the relative
            // logout URL below, MSW can't resolve request URLs against it and errors out
            await expectLogic(preflightLogic).toFinishAllListeners()

            const originalLocation = window.location
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: { ...originalLocation, href: originalLocation.href },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.returnToPostHog()
                }).toFinishAllListeners()

                expect(window.location.href).toBe('/admin/logout/?next=%2F')
            } finally {
                Object.defineProperty(window, 'location', {
                    configurable: true,
                    writable: true,
                    value: originalLocation,
                })
            }
        })
    })

    describe('loadUserSuccess listener', () => {
        it('clears expired session when user is impersonated', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
            }).toMatchValues({
                expiredSessionInfo: null,
                isSessionExpired: false,
            })

            expect(lemonToast.success).toHaveBeenCalledWith('Impersonation session renewed')
        })

        it('does nothing when expiredSessionInfo is null', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
            }).toMatchValues({
                expiredSessionInfo: null,
            })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })

        it('does not clear overlay when loaded user is not impersonated', async () => {
            const expiredInfo = { email: 'test@example.com', userId: 123, isImpersonatedUntil: null }
            logic.actions.setSessionExpired(expiredInfo)

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            }).toMatchValues({
                expiredSessionInfo: expiredInfo,
                isSessionExpired: true,
            })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })

        it('drops a stored ticket when loading as a non-impersonated user', async () => {
            logic.actions.setReturnToTicketContext({ ticketNumber: 42, email: 'a@example.com' })

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            }).toMatchValues({ returnToTicketContext: null })
        })

        it('drops a stored ticket when impersonating a different customer', async () => {
            logic.actions.setReturnToTicketContext({ ticketNumber: 42, email: 'someone-else@example.com' })

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
            }).toMatchValues({ returnToTicketContext: null })
        })

        it('keeps a stored ticket while still impersonating its customer', async () => {
            const context = { ticketNumber: 42, email: MOCK_IMPERSONATED_USER.email }
            logic.actions.setReturnToTicketContext(context)

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
            }).toMatchValues({ returnToTicketContext: context })
        })
    })

    describe('setPageVisible listener', () => {
        it('probes /api/users/@me/ and dispatches loadUserSuccess when session was renewed', async () => {
            useMocks({
                get: {
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
            })
            logic.actions.setSessionExpired({
                email: 'test@example.com',
                userId: 123,
                isImpersonatedUntil: null,
            })

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toDispatchActions(['loadUserSuccess'])
                .toFinishAllListeners()
        })

        it('does not probe /api/users/@me/ when there is no expired session', async () => {
            const fetchSpy = jest.spyOn(globalThis, 'fetch')

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            }).toFinishAllListeners()

            const probed = fetchSpy.mock.calls.some(
                ([url]) => typeof url === 'string' && url.includes('/api/users/@me/')
            )
            expect(probed).toBe(false)
            fetchSpy.mockRestore()
        })

        it('does nothing when page becomes hidden', async () => {
            const expiredInfo = { email: 'test@example.com', userId: 123, isImpersonatedUntil: null }
            logic.actions.setSessionExpired(expiredInfo)
            const fetchSpy = jest.spyOn(globalThis, 'fetch')

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(false)
            }).toFinishAllListeners()

            const probed = fetchSpy.mock.calls.some(
                ([url]) => typeof url === 'string' && url.includes('/api/users/@me/')
            )
            expect(probed).toBe(false)
            expect(logic.values.expiredSessionInfo).toEqual(expiredInfo)
            fetchSpy.mockRestore()
        })

        it('keeps overlay up when /api/users/@me/ returns 401 on page focus', async () => {
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, {}],
                },
            })
            const expiredInfo = {
                email: 'test@example.com',
                userId: 123,
                isImpersonatedUntil: null,
            }
            logic.actions.setSessionExpired(expiredInfo)

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    expiredSessionInfo: expiredInfo,
                    isSessionExpired: true,
                })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })

        it('keeps overlay up when is_impersonated_until has not advanced', async () => {
            const staleUntil = new Date(Date.now() - 60 * 1000).toISOString()
            const staleUser: UserType = {
                ...MOCK_IMPERSONATED_USER,
                is_impersonated_until: staleUntil,
            }
            useMocks({
                get: {
                    '/api/users/@me/': () => [200, staleUser],
                },
            })
            const expiredInfo = {
                email: 'test@example.com',
                userId: 123,
                isImpersonatedUntil: staleUntil,
            }
            logic.actions.setSessionExpired(expiredInfo)

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    expiredSessionInfo: expiredInfo,
                    isSessionExpired: true,
                })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })
    })

    describe('security', () => {
        it.each([
            { readOnly: true, expected: 'true' },
            { readOnly: false, expected: 'false' },
        ])('sends read_only=$expected when readOnly is $readOnly', async ({ readOnly, expected }) => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            const fetchSpy = jest.spyOn(globalThis, 'fetch')

            useMocks({
                get: {
                    '/admin/auth_check': () => [200, {}],
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.reImpersonate('support ticket #456', readOnly)
            })
                .toDispatchActions(['loadUser'])
                .toFinishAllListeners()

            const loginCall = fetchSpy.mock.calls.find(
                ([url]) => typeof url === 'string' && url.includes('/admin/login/user/')
            )
            expect(loginCall).toBeTruthy()
            const body = new URLSearchParams(loginCall![1]?.body as string)
            expect(body.get('read_only')).toBe(expected)
            expect(body.get('reason')).toBe('support ticket #456')

            fetchSpy.mockRestore()
        })

        it('ignores OAuth2 postMessage events from different origins', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123, isImpersonatedUntil: null })

            useMocks({
                get: {
                    '/admin/auth_check': () => [401, {}],
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            const mockWindow = { closed: false } as Window
            const openSpy = jest.spyOn(window, 'open').mockReturnValue(mockWindow)

            const promise = expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })

            // Wait for popup to open
            await new Promise((resolve) => setTimeout(resolve, 100))

            // Send postMessage from a different origin — must be ignored
            window.dispatchEvent(
                new MessageEvent('message', {
                    origin: 'https://evil.example.com',
                    data: { type: 'oauth2_complete' },
                })
            )

            // Give the listener time to (incorrectly) process the message
            await new Promise((resolve) => setTimeout(resolve, 100))

            // The cross-origin message was correctly ignored, so the flow is still blocked.
            // Only a legitimate same-origin `oauth2_complete` unblocks it.
            window.dispatchEvent(
                new MessageEvent('message', {
                    origin: window.location.origin,
                    data: { type: 'oauth2_complete' },
                })
            )

            await promise.toDispatchActions(['loadUser']).toFinishAllListeners()

            openSpy.mockRestore()
        })
    })

    describe('re-impersonation from another tab', () => {
        it('clears overlay when page regains focus and session was renewed in another tab', async () => {
            // Scenario: Tab 1 has an expired overlay for User A.
            // In another tab, staff starts impersonating User B.
            // When Tab 1 regains focus, the listener probes /api/users/@me/ directly
            // and hands the fresh user to loadUserSuccess, which clears the overlay.

            const userFromOtherTab: UserType = {
                ...MOCK_IMPERSONATED_USER,
                email: 'user-b@example.com',
                id: 200,
            }
            useMocks({
                get: {
                    '/api/users/@me/': () => [200, userFromOtherTab],
                },
            })
            logic.actions.setSessionExpired({
                email: 'user-a@example.com',
                userId: 100,
                isImpersonatedUntil: null,
            })

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toDispatchActions(['loadUserSuccess'])
                .toFinishAllListeners()

            expect(logic.values.expiredSessionInfo).toBeNull()
            expect(logic.values.isSessionExpired).toBe(false)
            expect(logic.values.isReImpersonating).toBe(false)
            expect(lemonToast.success).toHaveBeenCalledWith('Impersonation session renewed')
        })

        it('keeps overlay when page regains focus but session is not impersonated', async () => {
            // Scenario: Tab 1 has an expired overlay. The other tab logged out
            // of impersonation entirely. When Tab 1 regains focus, /api/users/@me/
            // returns a non-impersonated staff user — the overlay should stay.

            useMocks({
                get: {
                    '/api/users/@me/': () => [200, MOCK_DEFAULT_USER],
                },
            })
            const expiredInfo = {
                email: 'user-a@example.com',
                userId: 100,
                isImpersonatedUntil: null,
            }
            logic.actions.setSessionExpired(expiredInfo)

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    expiredSessionInfo: expiredInfo,
                    isSessionExpired: true,
                })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })
    })

    describe('orderedMembers selector', () => {
        it('sorts the current user in place by power then name, not hoisted to the top', async () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_IMPERSONATED_USER,
                first_name: 'Casey',
                last_name: '',
                organization: { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Admin },
            })

            membersLogic.actions.loadAllMembersSuccess([
                mockMember('Zed', OrganizationMembershipLevel.Owner, 10, 'uuid-zed'),
                mockMember('Ash', OrganizationMembershipLevel.Admin, 11, 'uuid-ash'),
                mockMember('Bea', OrganizationMembershipLevel.Member, 12, 'uuid-bea'),
            ])

            // Owner first (Zed), then Admins A→Z (Ash before the current user Casey), then Member (Bea).
            const names = logic.values.orderedMembers.map((member) => member.user.first_name)
            expect(names).toEqual(['Zed', 'Ash', 'Casey', 'Bea'])
            expect(logic.values.hasOtherMembers).toBe(true)
        })

        // Covers both that the current user shows before the members list loads (via `me`, guarding
        // the instant-display behavior) and that they remain when no one else is in the org.
        it.each([
            { scenario: 'before the members list has loaded', loadSelfOnly: false },
            { scenario: 'when they are the only member', loadSelfOnly: true },
        ])('lists just the current user $scenario', async ({ loadSelfOnly }) => {
            userLogic.actions.loadUserSuccess({ ...MOCK_IMPERSONATED_USER, first_name: 'Casey', last_name: '' })

            if (loadSelfOnly) {
                membersLogic.actions.loadAllMembersSuccess([
                    mockMember('Casey', OrganizationMembershipLevel.Member, 1, MOCK_DEFAULT_USER.uuid),
                ])
            }

            expect(logic.values.orderedMembers.map((member) => member.user.first_name)).toEqual(['Casey'])
            expect(logic.values.hasOtherMembers).toBe(false)
        })
    })

    describe('changeUser listener', () => {
        function mockLocationReload(): { reload: jest.Mock; restore: () => void } {
            const originalLocation = window.location
            const reload = jest.fn()
            Object.defineProperty(window, 'location', {
                configurable: true,
                writable: true,
                value: { ...originalLocation, reload },
            })
            return {
                reload,
                restore: () =>
                    Object.defineProperty(window, 'location', {
                        configurable: true,
                        writable: true,
                        value: originalLocation,
                    }),
            }
        }

        it.each([
            { readOnly: true, expected: 'true' },
            { readOnly: false, expected: 'false' },
        ])('sends read_only=$expected matching the current mode', async ({ readOnly, expected }) => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_IMPERSONATED_USER,
                is_impersonated_read_only: readOnly,
            })

            const fetchSpy = jest.spyOn(globalThis, 'fetch')
            const { reload, restore } = mockLocationReload()

            useMocks({
                get: {
                    '/admin/auth_check': () => [200, {}],
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.changeUser(456, 'support ticket #123')
                }).toFinishAllListeners()

                const loginCall = fetchSpy.mock.calls.find(
                    ([url]) => typeof url === 'string' && url.includes('/admin/login/user/456/')
                )
                expect(loginCall).toBeTruthy()
                const body = new URLSearchParams(loginCall![1]?.body as string)
                expect(body.get('reason')).toBe('support ticket #123')
                expect(body.get('read_only')).toBe(expected)
                expect(reload).toHaveBeenCalled()
            } finally {
                restore()
                fetchSpy.mockRestore()
            }
        })

        it('uses an explicitly passed reason over the persisted one', async () => {
            userLogic.actions.loadUserSuccess({ ...MOCK_IMPERSONATED_USER, is_impersonated_reason: 'persisted reason' })

            const fetchSpy = jest.spyOn(globalThis, 'fetch')
            const { restore } = mockLocationReload()

            try {
                await expectLogic(logic, () => {
                    logic.actions.changeUser(456, 'fresh reason')
                }).toFinishAllListeners()

                const loginCall = fetchSpy.mock.calls.find(
                    ([url]) => typeof url === 'string' && url.includes('/admin/login/user/456/')
                )
                const body = new URLSearchParams(loginCall![1]?.body as string)
                expect(body.get('reason')).toBe('fresh reason')
            } finally {
                restore()
                fetchSpy.mockRestore()
            }
        })

        it('does not call the endpoint when no reason is available', async () => {
            userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
            const fetchSpy = jest.spyOn(globalThis, 'fetch')

            await expectLogic(logic, () => {
                logic.actions.changeUser(456)
            })
                .toDispatchActions(['changeUserFailure'])
                .toFinishAllListeners()
                .toMatchValues({ isChangingUser: false })

            const loginCall = fetchSpy.mock.calls.find(
                ([url]) => typeof url === 'string' && url.includes('/admin/login/user/')
            )
            expect(loginCall).toBeUndefined()
            expect(lemonToast.error).toHaveBeenCalled()
            fetchSpy.mockRestore()
        })

        it('shows an error toast and resets state on failure', async () => {
            userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)

            const { reload, restore } = mockLocationReload()

            useMocks({
                get: {
                    '/admin/auth_check': () => [200, {}],
                },
                post: {
                    '/admin/login/user/:id/': () => [403, { detail: 'Forbidden' }],
                },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.changeUser(456, 'support ticket #123')
                })
                    .toDispatchActions(['changeUserFailure'])
                    .toFinishAllListeners()
                    .toMatchValues({ isChangingUser: false })

                expect(lemonToast.error).toHaveBeenCalled()
                expect(reload).not.toHaveBeenCalled()
            } finally {
                restore()
            }
        })
    })
})
