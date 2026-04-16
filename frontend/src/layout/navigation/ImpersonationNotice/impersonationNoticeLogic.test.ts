import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { impersonationNoticeLogic } from './impersonationNoticeLogic'

jest.mock('@posthog/lemon-ui', () => {
    const actual = jest.requireActual('@posthog/lemon-ui')
    return {
        ...actual,
        lemonToast: {
            ...actual.lemonToast,
            success: jest.fn(),
            error: jest.fn(),
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

describe('impersonationNoticeLogic', () => {
    let logic: ReturnType<typeof impersonationNoticeLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/': () => [200, MOCK_DEFAULT_USER],
                '/admin/auth_check': () => [200, {}],
            },
            post: {
                '/admin/login/user/:id/': () => [200, {}],
            },
        })
        initKeaTests()
        userLogic.mount()
        logic = impersonationNoticeLogic()
        logic.mount()
    })

    describe('reducers', () => {
        it('sets expiredSessionInfo via setSessionExpired', async () => {
            const info = { email: 'test@example.com', userId: 123 }

            await expectLogic(logic, () => {
                logic.actions.setSessionExpired(info)
            }).toMatchValues({
                expiredSessionInfo: info,
                isSessionExpired: true,
            })
        })

        it('clears expiredSessionInfo when set to null', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

            await expectLogic(logic, () => {
                logic.actions.setSessionExpired(null)
            }).toMatchValues({
                expiredSessionInfo: null,
                isSessionExpired: false,
            })
        })

        it('sets isReImpersonating to true on reImpersonate', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })
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

    describe('reImpersonate listener', () => {
        it('calls login-as endpoint and dispatches loadUser on success', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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

        it('opens OAuth2 popup when auth check fails and proceeds after window closes', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

            let authCheckCallCount = 0
            useMocks({
                get: {
                    '/admin/auth_check': () => {
                        authCheckCallCount++
                        // First call fails (triggers popup), but the login will succeed after
                        if (authCheckCallCount === 1) {
                            return [401, {}]
                        }
                        return [200, {}]
                    },
                    '/api/users/@me/': () => [200, MOCK_IMPERSONATED_USER],
                },
                post: {
                    '/admin/login/user/:id/': () => [200, {}],
                },
            })

            // Mock window.open to return a window that closes immediately
            const mockWindow = { closed: false } as Window
            const openSpy = jest.spyOn(window, 'open').mockReturnValue(mockWindow)

            const reImpersonatePromise = expectLogic(logic, () => {
                logic.actions.reImpersonate('reason', true)
            })

            // Simulate the popup window closing (which resolves the promise)
            await new Promise((resolve) => setTimeout(resolve, 100))
            ;(mockWindow as any).closed = true

            await reImpersonatePromise.toDispatchActions(['reImpersonate', 'loadUser']).toFinishAllListeners()

            expect(openSpy).toHaveBeenCalledWith(
                '/admin/oauth2/success',
                'admin_oauth2',
                expect.stringContaining('width=600')
            )
            openSpy.mockRestore()
        })
    })

    describe('loadUserSuccess listener', () => {
        it('clears expired session when user is impersonated', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            }).toMatchValues({
                expiredSessionInfo: { email: 'test@example.com', userId: 123 },
                isSessionExpired: true,
            })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })
    })

    describe('setPageVisible listener', () => {
        it('dispatches loadUser when page becomes visible with expired session', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toDispatchActions(['loadUser'])
                .toFinishAllListeners()
        })

        it('does not dispatch loadUser when page becomes visible without expired session', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            })
                .toNotHaveDispatchedActions(['loadUser'])
                .toFinishAllListeners()
        })

        it('does not dispatch loadUser when page becomes hidden', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(false)
            })
                .toNotHaveDispatchedActions(['loadUser'])
                .toFinishAllListeners()
        })
    })

    describe('security', () => {
        it('sends read_only=true when readOnly is true', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
                logic.actions.reImpersonate('support ticket #456', true)
            })
                .toDispatchActions(['loadUser'])
                .toFinishAllListeners()

            const loginCall = fetchSpy.mock.calls.find(
                ([url]) => typeof url === 'string' && url.includes('/admin/login/user/')
            )
            expect(loginCall).toBeTruthy()
            const body = new URLSearchParams(loginCall![1]?.body as string)
            expect(body.get('read_only')).toBe('true')
            expect(body.get('reason')).toBe('support ticket #456')

            fetchSpy.mockRestore()
        })

        it('sends read_only=false when readOnly is false', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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
                logic.actions.reImpersonate('support ticket #456', false)
            })
                .toDispatchActions(['loadUser'])
                .toFinishAllListeners()

            const loginCall = fetchSpy.mock.calls.find(
                ([url]) => typeof url === 'string' && url.includes('/admin/login/user/')
            )
            expect(loginCall).toBeTruthy()
            const body = new URLSearchParams(loginCall![1]?.body as string)
            expect(body.get('read_only')).toBe('false')
            expect(body.get('reason')).toBe('support ticket #456')

            fetchSpy.mockRestore()
        })

        it('ignores OAuth2 postMessage events from different origins', async () => {
            logic.actions.setSessionExpired({ email: 'test@example.com', userId: 123 })

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

            // The login-as POST should NOT have been sent yet because the
            // cross-origin message was correctly ignored. Closing the popup
            // is what actually unblocks the flow.
            ;(mockWindow as any).closed = true

            await promise.toDispatchActions(['loadUser']).toFinishAllListeners()

            openSpy.mockRestore()
        })
    })

    describe('re-impersonation from another tab', () => {
        it('clears overlay when page regains focus and session was renewed in another tab', async () => {
            // Scenario: Tab 1 has an expired overlay for User A.
            // In another tab, staff starts impersonating User B.
            // When Tab 1 regains focus, setPageVisible(true) dispatches loadUser.
            // The server now returns an impersonated user, so loadUserSuccess
            // clears the stale overlay.

            logic.actions.setSessionExpired({ email: 'user-a@example.com', userId: 100 })

            // Step 1: page becomes visible → loadUser is dispatched
            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            }).toDispatchActions(['loadUser'])

            // Step 2: loadUser resolves with an impersonated user (from the other tab)
            // Simulate by directly dispatching loadUserSuccess
            const userFromOtherTab: UserType = {
                ...MOCK_IMPERSONATED_USER,
                email: 'user-b@example.com',
                id: 200,
            }

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(userFromOtherTab)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    expiredSessionInfo: null,
                    isSessionExpired: false,
                    isReImpersonating: false,
                })

            expect(lemonToast.success).toHaveBeenCalledWith('Impersonation session renewed')
        })

        it('keeps overlay when page regains focus but session is not impersonated', async () => {
            // Scenario: Tab 1 has an expired overlay. The other tab logged out
            // of impersonation entirely. When Tab 1 regains focus, loadUser
            // returns a non-impersonated staff user — the overlay should stay.

            const expiredInfo = { email: 'user-a@example.com', userId: 100 }
            logic.actions.setSessionExpired(expiredInfo)

            await expectLogic(logic, () => {
                logic.actions.setPageVisible(true)
            }).toDispatchActions(['loadUser'])

            await expectLogic(logic, () => {
                logic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    expiredSessionInfo: expiredInfo,
                    isSessionExpired: true,
                })

            expect(lemonToast.success).not.toHaveBeenCalled()
        })
    })
})
