import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { cleanToolbarAuthHash, OAUTH_LOCALSTORAGE_KEY, PKCE_STORAGE_KEY, readToolbarAuthHash } from '~/toolbar/utils'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

/** Mock fetch so the HEAD check succeeds and then the token exchange succeeds. */
function mockTokenExchangeSuccess(): void {
    ;(global.fetch as jest.Mock).mockImplementation((url: string) => {
        if (typeof url === 'string' && url.endsWith('/toolbar_oauth/check')) {
            return Promise.resolve({ ok: true, status: 200 })
        }
        return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }),
        })
    })
}

describe('toolbar toolbarConfigLogic', () => {
    let mockOpen: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        sessionStorage.clear()
        ;(global.fetch as jest.Mock).mockClear()
        mockOpen = jest.spyOn(window, 'open').mockReturnValue({} as Window)
    })

    afterEach(() => {
        mockOpen.mockRestore()
    })

    it('is not authenticated without any token', () => {
        const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
        logic.mount()
        expectLogic(logic).toMatchValues({ isAuthenticated: false })
    })

    it('is authenticated with accessToken', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            accessToken: 'pha_oauth_token',
            refreshToken: 'phr_refresh',
            clientId: 'client-id',
        })
        logic.mount()
        expectLogic(logic).toMatchValues({ isAuthenticated: true })
    })

    it('setOAuthTokens updates tokens', () => {
        const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.setOAuthTokens('pha_new', 'phr_new', 'client-123')
        }).toMatchValues({
            accessToken: 'pha_new',
            refreshToken: 'phr_new',
            clientId: 'client-123',
            isAuthenticated: true,
        })
    })

    it('logout clears all tokens', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            accessToken: 'access',
            refreshToken: 'refresh',
            clientId: 'client',
        })
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.logout()
        }).toMatchValues({
            accessToken: null,
            refreshToken: null,
            clientId: null,
            isAuthenticated: false,
        })
    })

    it('tokenExpired clears OAuth tokens', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            accessToken: 'access',
            refreshToken: 'refresh',
            clientId: 'client',
        })
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.tokenExpired()
        }).toMatchValues({
            accessToken: null,
            refreshToken: null,
            clientId: null,
            isAuthenticated: false,
        })
    })

    it('normalizes uiHost to not end with a slash', () => {
        const logic = toolbarConfigLogic.build({
            posthog: { config: { ui_host: 'https://selfhosted.example.com/' } } as any,
        } as any)
        logic.mount()
        expect(logic.values.uiHost).toBe('https://selfhosted.example.com')
    })

    describe('uiHost resolution', () => {
        it('prefers explicit uiHost prop over everything else', () => {
            const logic = toolbarConfigLogic.build({
                uiHost: 'https://us.posthog.com',
                posthog: { requestRouter: { uiHost: 'https://should-not-be-used.com' }, config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://us.posthog.com')
        })

        it.each([
            ['https://us.posthog.com', 'https://us.posthog.com'],
            ['https://eu.posthog.com', 'https://eu.posthog.com'],
        ])('uses requestRouter.uiHost when no explicit uiHost prop', (requestRouterUiHost, expected) => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://should-not-be-used',
                posthog: { requestRouter: { uiHost: requestRouterUiHost }, config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe(expected)
        })

        it('uses requestRouter.uiHost even when apiURL is a reverse proxy', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'https://myproxy.example.com/ingest',
                posthog: { requestRouter: { uiHost: 'https://us.posthog.com' }, config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://us.posthog.com')
        })

        it('falls back to ui_host config when no requestRouter', () => {
            const logic = toolbarConfigLogic.build({
                posthog: {
                    config: { ui_host: 'https://my-posthog.example.com' },
                } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://my-posthog.example.com')
        })

        it('falls back to apiURL when no requestRouter and no ui_host', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'https://selfhosted.example.com',
                posthog: { config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://selfhosted.example.com')
        })

        it.each(['javascript:alert(1)//', 'data:text/html,<script>alert(1)</script>', 'vbscript:msgbox'])(
            'rejects uiHost with dangerous scheme: %s',
            (maliciousHost) => {
                const logic = toolbarConfigLogic.build({
                    uiHost: maliciousHost,
                    apiURL: 'https://fallback.example.com',
                    posthog: { config: {} } as any,
                } as any)
                logic.mount()
                // Should fall through to apiURL instead of using the malicious value
                expect(logic.values.uiHost).toBe('https://fallback.example.com')
            }
        )

        it('accepts valid https uiHost', () => {
            const logic = toolbarConfigLogic.build({
                uiHost: 'https://app.posthog.com',
                apiURL: 'https://fallback.example.com',
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://app.posthog.com')
        })

        it('accepts valid http uiHost', () => {
            const logic = toolbarConfigLogic.build({
                uiHost: 'http://localhost:8000',
                apiURL: 'https://fallback.example.com',
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('http://localhost:8000')
        })
    })

    describe('OAuth localStorage restoration', () => {
        it('restores OAuth from localStorage when no tokens in props', () => {
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            expectLogic(logic).toMatchValues({
                accessToken: 'stored-access',
                refreshToken: 'stored-refresh',
                clientId: 'stored-client',
                isAuthenticated: true,
            })
        })

        it('does not overwrite when accessToken already exists in props', () => {
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'existing-access',
                refreshToken: 'existing-refresh',
                clientId: 'existing-client',
            })
            logic.mount()

            expectLogic(logic).toMatchValues({ accessToken: 'existing-access', isAuthenticated: true })
        })
    })

    describe('toolbar re-launch and token persistence', () => {
        afterEach(() => {
            window.history.pushState({}, '', '/')
        })

        it('restores tokens from OAuth localStorage when posthog-js re-launches without tokens', () => {
            // posthog-js overwrites _postHogToolbarParams on re-launch, losing tokens.
            // OAuth tokens are persisted separately in _postHogToolbarOAuth.
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                token: 'phc_test',
                // No accessToken — simulates posthog-js overwrite
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                accessToken: 'stored-access',
                refreshToken: 'stored-refresh',
                clientId: 'stored-client',
                isAuthenticated: true,
            })
        })

        it('does not restore stored tokens when props already include tokens', () => {
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'old-stored',
                    refreshToken: 'old-stored-refresh',
                    clientId: 'old-stored-client',
                })
            )
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'props-access',
                refreshToken: 'props-refresh',
                clientId: 'props-client',
            })
            logic.mount()

            expectLogic(logic).toMatchValues({ accessToken: 'props-access' })
        })

        it('code exchange takes priority over stored tokens', async () => {
            // If a fresh code is in the hash, exchange it instead of restoring old tokens
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'old-stored',
                    refreshToken: 'old-refresh',
                    clientId: 'old-client',
                })
            )
            localStorage.setItem(PKCE_STORAGE_KEY, JSON.stringify({ verifier: 'test-verifier', ts: Date.now() }))
            window.history.pushState({}, '', '/#__posthog_toolbar=code:fresh,client_id:new-client')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                accessToken: 'new-access',
                refreshToken: 'new-refresh',
                isAuthenticated: true,
            })
        })

        it('falls back to stored tokens when code exchange fails due to expired PKCE', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            // PKCE verifier expired
            localStorage.setItem(
                PKCE_STORAGE_KEY,
                JSON.stringify({ verifier: 'expired-verifier', ts: Date.now() - 11 * 60 * 1000 })
            )
            window.history.pushState({}, '', '/#__posthog_toolbar=code:stale,client_id:some-client')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                accessToken: 'stored-access',
                refreshToken: 'stored-refresh',
                clientId: 'stored-client',
                isAuthenticated: true,
            })
            warnSpy.mockRestore()
        })

        it('falls back to stored tokens when no PKCE verifier exists', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            localStorage.removeItem(PKCE_STORAGE_KEY)
            window.history.pushState({}, '', '/#__posthog_toolbar=code:stale,client_id:some-client')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                accessToken: 'stored-access',
                isAuthenticated: true,
            })
            warnSpy.mockRestore()
        })

        it('resets authStatus to idle after failed code exchange with fallback', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.setItem(
                OAUTH_LOCALSTORAGE_KEY,
                JSON.stringify({
                    accessToken: 'stored-access',
                    refreshToken: 'stored-refresh',
                    clientId: 'stored-client',
                })
            )
            localStorage.removeItem(PKCE_STORAGE_KEY)
            window.history.pushState({}, '', '/#__posthog_toolbar=code:stale,client_id:some-client')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                authStatus: 'idle',
                isAuthenticated: true,
            })
            warnSpy.mockRestore()
        })

        it('remains unauthenticated when code exchange fails and no stored tokens exist', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
            localStorage.setItem(
                PKCE_STORAGE_KEY,
                JSON.stringify({ verifier: 'expired-verifier', ts: Date.now() - 11 * 60 * 1000 })
            )
            window.history.pushState({}, '', '/#__posthog_toolbar=code:stale,client_id:some-client')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                isAuthenticated: false,
                accessToken: null,
            })
            warnSpy.mockRestore()
        })

        it('setOAuthTokens persists to separate OAuth localStorage key', () => {
            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            logic.actions.setOAuthTokens('new-access', 'new-refresh', 'new-client')

            const stored = JSON.parse(localStorage.getItem(OAUTH_LOCALSTORAGE_KEY) || '{}')
            expect(stored).toEqual({
                accessToken: 'new-access',
                refreshToken: 'new-refresh',
                clientId: 'new-client',
            })
        })

        it('logout clears both localStorage keys', () => {
            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            // Authenticate first so tokens are persisted
            logic.actions.setOAuthTokens('access', 'refresh', 'client')
            expect(localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)).not.toBeNull()

            logic.actions.logout()

            expect(localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)).toBeNull()
            expect(localStorage.getItem('_postHogToolbarParams')).toBeNull()
            expect(localStorage.getItem(PKCE_STORAGE_KEY)).toBeNull()
        })

        it('tokenExpired clears OAuth localStorage key', () => {
            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            logic.actions.setOAuthTokens('access', 'refresh', 'client')
            expect(localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)).not.toBeNull()

            logic.actions.tokenExpired()

            expect(localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)).toBeNull()
        })

        it('survives mount/unmount/remount cycle with tokens intact', () => {
            // First mount: set tokens
            const logic1 = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic1.mount()
            logic1.actions.setOAuthTokens('persisted-access', 'persisted-refresh', 'persisted-client')
            logic1.unmount()

            // Second mount: tokens should be restored from OAuth localStorage
            const logic2 = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic2.mount()

            expectLogic(logic2).toMatchValues({
                accessToken: 'persisted-access',
                refreshToken: 'persisted-refresh',
                clientId: 'persisted-client',
                isAuthenticated: true,
            })
        })

        it('handles corrupted OAuth localStorage gracefully', () => {
            localStorage.setItem(OAUTH_LOCALSTORAGE_KEY, 'not-valid-json{{{')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            expectLogic(logic).toMatchValues({ isAuthenticated: false, accessToken: null })
        })

        it('handles partial OAuth localStorage data gracefully', () => {
            localStorage.setItem(OAUTH_LOCALSTORAGE_KEY, JSON.stringify({ accessToken: 'only-access' }))

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            // Missing refreshToken and clientId — should not restore
            expectLogic(logic).toMatchValues({ isAuthenticated: false, accessToken: null })
        })
    })

    describe('token refresh on 401', () => {
        it('retries request with new token after successful refresh', async () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'old-access',
                refreshToken: 'old-refresh',
                clientId: 'client-id',
            })
            logic.mount()

            let apiCallCount = 0
            ;(global.fetch as jest.Mock).mockImplementation((url: string) => {
                if (url.includes('toolbar_oauth_refresh')) {
                    return Promise.resolve({
                        ok: true,
                        status: 200,
                        json: () =>
                            Promise.resolve({
                                access_token: 'new-access',
                                refresh_token: 'new-refresh',
                                expires_in: 3600,
                            }),
                    })
                }
                apiCallCount++
                if (apiCallCount === 1) {
                    return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) })
                }
                return Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve({ results: ['data'] }),
                })
            })

            const response = await toolbarFetch('/api/projects/@current/actions/')

            expect(response.status).toBe(200)
            expect(logic.values.accessToken).toBe('new-access')
            expect(logic.values.refreshToken).toBe('new-refresh')
        })

        it('calls tokenExpired when refresh fails', async () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'old-access',
                refreshToken: 'old-refresh',
                clientId: 'client-id',
            })
            logic.mount()
            ;(global.fetch as jest.Mock).mockImplementation((url: string) => {
                if (url.includes('toolbar_oauth_refresh')) {
                    return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({}) })
                }
                return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) })
            })

            await toolbarFetch('/api/projects/@current/actions/')

            expect(logic.values.accessToken).toBeNull()
            expect(logic.values.isAuthenticated).toBe(false)
        })

        it('does not retry when response is not 401', async () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'access-token',
                refreshToken: 'refresh-token',
                clientId: 'client-id',
            })
            logic.mount()
            ;(global.fetch as jest.Mock).mockClear() // clear the uiHost check call from afterMount
            ;(global.fetch as jest.Mock).mockImplementation(() =>
                Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve({ results: [] }),
                })
            )

            const response = await toolbarFetch('/api/projects/@current/actions/')

            expect(response.status).toBe(200)
            // Only one fetch call (no refresh)
            expect((global.fetch as jest.Mock).mock.calls).toHaveLength(1)
            expect(logic.values.accessToken).toBe('access-token')
        })
    })

    describe('authorization code extraction and hash cleanup', () => {
        let replaceStateSpy: jest.SpyInstance

        beforeEach(() => {
            replaceStateSpy = jest.spyOn(window.history, 'replaceState').mockImplementation(() => {})
            const pkcePayload = JSON.stringify({ verifier: 'test-verifier', ts: Date.now() })
            localStorage.setItem(PKCE_STORAGE_KEY, pkcePayload)
        })

        afterEach(() => {
            replaceStateSpy.mockRestore()
            window.history.pushState({}, '', '/')
        })

        it.each([
            ['toolbar-only hash is fully removed', '#__posthog_toolbar=code:abc,client_id:xyz', '/'],
            [
                'preserves original fragment before toolbar param',
                '#section1&__posthog_toolbar=code:abc,client_id:xyz',
                '/#section1',
            ],
            [
                'preserves multi-part original fragment',
                '#/dashboard&tab=1&__posthog_toolbar=code:abc,client_id:xyz',
                '/#/dashboard&tab=1',
            ],
            ['handles percent-encoded delimiters', '#__posthog_toolbar=code%3Aabc%2Cclient_id%3Axyz', '/'],
        ])('%s', (_label, hash, expectedUrl) => {
            jest.useFakeTimers()
            window.history.pushState({}, '', `/${hash}`)

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            // Hash cleanup is deferred to avoid triggering SPA router re-renders
            expect(replaceStateSpy).not.toHaveBeenCalled()
            jest.advanceTimersByTime(500)
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', expectedUrl)
            jest.useRealTimers()
        })

        it('uses uiHost-derived URLs for token exchange', async () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({
                posthog: { config: { ui_host: 'https://us.posthog.com' } } as any,
            } as any)
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                accessToken: 'new-access',
                isAuthenticated: true,
            })

            // [0] = HEAD check, [1] = token exchange
            expect((global.fetch as jest.Mock).mock.calls[0][0]).toBe('https://us.posthog.com/toolbar_oauth/check')
            const fetchCall = (global.fetch as jest.Mock).mock.calls[1]
            expect(fetchCall[0]).toBe('https://us.posthog.com/oauth/token/')
            const body = new URLSearchParams(fetchCall[1].body)
            expect(body.get('redirect_uri')).toBe('https://us.posthog.com/toolbar_oauth/callback')
        })

        it('does not trigger temporaryToken migration during code exchange', async () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                temporaryToken: 'old-temp-token',
            })
            logic.mount()

            await expectLogic(logic).delay(0).toNotHaveDispatchedActions(['tokenExpired'])
        })

        it('cleans up localStorage PKCE key after exchange', async () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            // Wait for HEAD check + token exchange to complete
            await expectLogic(logic).delay(0)

            expect(localStorage.getItem(PKCE_STORAGE_KEY)).toBeNull()
        })

        it('aborts token exchange when PKCE verifier has expired', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            const expiredPayload = JSON.stringify({ verifier: 'test-verifier', ts: Date.now() - 11 * 60 * 1000 })
            localStorage.setItem(PKCE_STORAGE_KEY, expiredPayload)

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: PKCE verifier expired')
            // HEAD check fires but token exchange does not
            expect((global.fetch as jest.Mock).mock.calls).toHaveLength(1)
            expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/toolbar_oauth/check')
            warnSpy.mockRestore()
        })

        it('aborts token exchange when PKCE data is corrupted', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.setItem(PKCE_STORAGE_KEY, 'not-valid-json{{{')

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: no PKCE verifier found, cannot exchange code')
            // HEAD check fires but token exchange does not
            expect((global.fetch as jest.Mock).mock.calls).toHaveLength(1)
            expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/toolbar_oauth/check')
            warnSpy.mockRestore()
        })

        it('aborts token exchange when no PKCE data exists', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.removeItem(PKCE_STORAGE_KEY)

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: no PKCE verifier found, cannot exchange code')
            // HEAD check fires but token exchange does not
            expect((global.fetch as jest.Mock).mock.calls).toHaveLength(1)
            expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/toolbar_oauth/check')
            warnSpy.mockRestore()
        })
    })

    describe('readToolbarAuthHash', () => {
        afterEach(() => {
            window.history.pushState({}, '', '/')
        })

        it('returns code and clientId from hash without modifying the URL', () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            const replaceStateSpy = jest.spyOn(window.history, 'replaceState')
            const result = readToolbarAuthHash()
            expect(result).toEqual({ code: 'abc', clientId: 'xyz' })
            expect(replaceStateSpy).not.toHaveBeenCalled()
            replaceStateSpy.mockRestore()
        })

        it.each([
            ['empty hash', '/#', null],
            ['no hash at all', '/', null],
            ['unrelated hash', '/#some-other-hash', null],
            ['__posthog= without _toolbar', '/#__posthog=%7B%22action%22%3A%22ph_authorize%22%7D', null],
            ['missing code field', '/#__posthog_toolbar=client_id:xyz', null],
            ['missing client_id field', '/#__posthog_toolbar=code:abc', null],
            ['empty code value', '/#__posthog_toolbar=code:,client_id:xyz', null],
            ['similar-looking param that is not toolbar', '/#__posthog_toolbar_v2=code:abc,client_id:xyz', null],
        ])('returns null for: %s', (_label, url, expected) => {
            window.history.pushState({}, '', url)
            expect(readToolbarAuthHash()).toEqual(expected)
        })

        it.each([
            ['standard params', '/#__posthog_toolbar=code:abc,client_id:xyz', { code: 'abc', clientId: 'xyz' }],
            [
                'base64url-safe code with dashes and underscores',
                '/#__posthog_toolbar=code:a2gGQw68uN8fzaKelhTZZY-cuSDnP7H_x,client_id:QUKsGDyHrQqrbBwdMYaL2rmp2rPDfHJICOM5EZzY',
                {
                    code: 'a2gGQw68uN8fzaKelhTZZY-cuSDnP7H_x',
                    clientId: 'QUKsGDyHrQqrbBwdMYaL2rmp2rPDfHJICOM5EZzY',
                },
            ],
            [
                'preceded by hash-based SPA route',
                '/#/login&__posthog_toolbar=code:abc,client_id:xyz',
                { code: 'abc', clientId: 'xyz' },
            ],
            [
                'preceded by multiple hash params',
                '/#section1&tab=2&__posthog_toolbar=code:abc,client_id:xyz',
                { code: 'abc', clientId: 'xyz' },
            ],
            [
                'coexists with __posthog= param',
                '/#__posthog=%7B%7D&__posthog_toolbar=code:abc,client_id:xyz',
                { code: 'abc', clientId: 'xyz' },
            ],
            [
                'percent-encoded delimiters',
                '/#__posthog_toolbar=code%3Aabc%2Cclient_id%3Axyz',
                { code: 'abc', clientId: 'xyz' },
            ],
        ])('extracts params for: %s', (_label, url, expected) => {
            window.history.pushState({}, '', url)
            expect(readToolbarAuthHash()).toEqual(expected)
        })
    })

    describe('cleanToolbarAuthHash', () => {
        let replaceStateSpy: jest.SpyInstance

        beforeEach(() => {
            replaceStateSpy = jest.spyOn(window.history, 'replaceState').mockImplementation(() => {})
        })

        afterEach(() => {
            replaceStateSpy.mockRestore()
            window.history.pushState({}, '', '/')
        })

        it.each([
            ['toolbar-only hash', '/#__posthog_toolbar=code:abc,client_id:xyz', '/'],
            [
                'preserves fragment before toolbar param',
                '/#section1&__posthog_toolbar=code:abc,client_id:xyz',
                '/#section1',
            ],
            ['hash-based SPA route (Angular-style)', '/#/login&__posthog_toolbar=code:abc,client_id:xyz', '/#/login'],
            [
                'hash-based SPA route with nested path',
                '/#/dashboard/settings&__posthog_toolbar=code:abc,client_id:xyz',
                '/#/dashboard/settings',
            ],
            [
                'multi-part fragment with toolbar at end',
                '/#/dashboard&tab=1&__posthog_toolbar=code:abc,client_id:xyz',
                '/#/dashboard&tab=1',
            ],
            [
                'toolbar param in the middle of other params',
                '/#section1&__posthog_toolbar=code:abc,client_id:xyz&other=value',
                '/#section1&other=value',
            ],
            [
                'duplicate toolbar params from re-authentication',
                '/#__posthog_toolbar=code:old,client_id:old&__posthog_toolbar=code:new,client_id:new',
                '/',
            ],
            [
                'duplicate toolbar with SPA route preserved',
                '/#/app&__posthog_toolbar=code:old,client_id:old&__posthog_toolbar=code:new,client_id:new',
                '/#/app',
            ],
            [
                'preserves __posthog= param (owned by posthog-js)',
                '/#__posthog=%7B%7D&__posthog_toolbar=code:abc,client_id:xyz',
                '/#__posthog={}',
            ],
            ['percent-encoded toolbar param', '/#__posthog_toolbar=code%3Aabc%2Cclient_id%3Axyz', '/'],
            ['page has query string and hash', '/#__posthog_toolbar=code:abc,client_id:xyz', '/'],
        ])('cleanup: %s', (_label, hash, expectedUrl) => {
            window.history.pushState({}, '', hash)
            cleanToolbarAuthHash()
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', expectedUrl)
        })

        it.each([
            ['no hash at all', '/'],
            ['unrelated hash', '/#some-other-hash'],
            ['__posthog= without toolbar', '/#__posthog=%7B%7D'],
            ['empty hash', '/#'],
        ])('does nothing for: %s', (_label, url) => {
            window.history.pushState({}, '', url)
            cleanToolbarAuthHash()
            expect(replaceStateSpy).not.toHaveBeenCalled()
        })

        it('cleans hash on unmount even if deferred timeout has not fired', () => {
            jest.useFakeTimers()
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')

            const pkcePayload = JSON.stringify({ verifier: 'test-verifier', ts: Date.now() })
            localStorage.setItem(PKCE_STORAGE_KEY, pkcePayload)

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            expect(replaceStateSpy).not.toHaveBeenCalled()
            logic.unmount()
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/')
            jest.useRealTimers()
        })

        it('double unmount is safe (idempotent cleanup)', () => {
            jest.useFakeTimers()
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')

            const pkcePayload = JSON.stringify({ verifier: 'test-verifier', ts: Date.now() })
            localStorage.setItem(PKCE_STORAGE_KEY, pkcePayload)

            // Use a real replaceState so the URL actually changes after unmount
            replaceStateSpy.mockRestore()
            replaceStateSpy = jest.spyOn(window.history, 'replaceState')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()
            logic.unmount()

            expect(replaceStateSpy).toHaveBeenCalledTimes(1)

            // After first unmount the hash is gone. Second call is a no-op.
            replaceStateSpy.mockClear()
            cleanToolbarAuthHash()
            expect(replaceStateSpy).not.toHaveBeenCalled()
            jest.useRealTimers()
        })

        it('preserves page query string when cleaning hash', () => {
            // Simulate: https://example.com/page?q=search#__posthog_toolbar=code:abc,client_id:xyz
            window.history.pushState({}, '', '/page?q=search#__posthog_toolbar=code:abc,client_id:xyz')
            cleanToolbarAuthHash()
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/page?q=search')
        })
    })
})
