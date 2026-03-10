import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { cleanToolbarAuthHash, OAUTH_LOCALSTORAGE_KEY, PKCE_STORAGE_KEY } from '~/toolbar/utils'

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
            window.history.pushState({}, '', `/${hash}`)

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', expectedUrl)
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

    describe('cleanToolbarAuthHash', () => {
        let replaceStateSpy: jest.SpyInstance

        beforeEach(() => {
            replaceStateSpy = jest.spyOn(window.history, 'replaceState').mockImplementation(() => {})
        })

        afterEach(() => {
            replaceStateSpy.mockRestore()
            window.history.pushState({}, '', '/')
        })

        it('returns code and clientId from hash', () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            const result = cleanToolbarAuthHash()
            expect(result).toEqual({ code: 'abc', clientId: 'xyz' })
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/')
        })

        it('returns null when hash does not match', () => {
            window.history.pushState({}, '', '/#some-other-hash')
            const result = cleanToolbarAuthHash()
            expect(result).toBeNull()
            expect(replaceStateSpy).not.toHaveBeenCalled()
        })
    })
})
