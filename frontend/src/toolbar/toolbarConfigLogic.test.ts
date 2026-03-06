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

function mockTokenExchangeSuccess(): void {
    ;(global.fetch as jest.Mock).mockImplementation(() =>
        Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({ access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }),
        })
    )
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

    describe('uiHost cloud region detection', () => {
        it.each([
            ['us', 'https://us.posthog.com'],
            ['eu', 'https://eu.posthog.com'],
        ])('uses canonical %s cloud URL from requestRouter.region', (region, expected) => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://should-not-be-used',
                posthog: { requestRouter: { region }, config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe(expected)
        })

        it('uses cloud URL even when ui_host is misconfigured to ingestion domain', () => {
            const logic = toolbarConfigLogic.build({
                posthog: {
                    requestRouter: { region: 'eu' },
                    config: { ui_host: 'https://eu.i.posthog.com' },
                } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://eu.posthog.com')
        })

        it('uses cloud URL even when apiURL is a reverse proxy', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'https://myproxy.example.com/ingest',
                posthog: { requestRouter: { region: 'us' }, config: {} } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://us.posthog.com')
        })

        it('falls back to ui_host for custom region (self-hosted)', () => {
            const logic = toolbarConfigLogic.build({
                posthog: {
                    requestRouter: { region: 'custom' },
                    config: { ui_host: 'https://my-posthog.example.com' },
                } as any,
            } as any)
            logic.mount()
            expect(logic.values.uiHost).toBe('https://my-posthog.example.com')
        })

        it('falls back to apiURL when region is custom and no ui_host', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'https://selfhosted.example.com',
                posthog: { requestRouter: { region: 'custom' }, config: {} } as any,
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
            [
                'cleans hash with server-provided redirect_uri and token_endpoint',
                '#__posthog_toolbar=code:abc,client_id:xyz,redirect_uri:https%3A%2F%2Fexample.com%2Fcallback,token_endpoint:https%3A%2F%2Fexample.com%2Ftoken',
                '/',
            ],
        ])('%s', (_label, hash, expectedUrl) => {
            window.history.pushState({}, '', `/${hash}`)

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', expectedUrl)
        })

        it('uses server-provided token_endpoint and redirect_uri for token exchange', async () => {
            const serverTokenEndpoint = 'https://internal.posthog.com/oauth/token/'
            const serverRedirectUri = 'https://internal.posthog.com/toolbar_oauth/callback'
            const encodedEndpoint = encodeURIComponent(serverTokenEndpoint)
            const encodedRedirectUri = encodeURIComponent(serverRedirectUri)

            window.history.pushState(
                {},
                '',
                `/#__posthog_toolbar=code:abc,client_id:xyz,redirect_uri:${encodedRedirectUri},token_endpoint:${encodedEndpoint}`
            )
            mockTokenExchangeSuccess()

            const logic = toolbarConfigLogic.build({ apiURL: 'http://external-proxy.com' })
            logic.mount()

            await expectLogic(logic).delay(0).toMatchValues({
                accessToken: 'new-access',
                isAuthenticated: true,
            })

            const fetchCall = (global.fetch as jest.Mock).mock.calls[0]
            expect(fetchCall[0]).toBe(serverTokenEndpoint)
            const body = new URLSearchParams(fetchCall[1].body)
            expect(body.get('redirect_uri')).toBe(serverRedirectUri)
        })

        it('falls back to uiHost-derived URLs when server does not provide them', async () => {
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

            const fetchCall = (global.fetch as jest.Mock).mock.calls[0]
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

            await expectLogic(logic).delay(0)

            expect(localStorage.getItem(PKCE_STORAGE_KEY)).toBeNull()
        })

        it('aborts token exchange when PKCE verifier has expired', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            const expiredPayload = JSON.stringify({ verifier: 'test-verifier', ts: Date.now() - 11 * 60 * 1000 })
            localStorage.setItem(PKCE_STORAGE_KEY, expiredPayload)

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: PKCE verifier expired')
            expect(global.fetch).not.toHaveBeenCalled()
            warnSpy.mockRestore()
        })

        it('aborts token exchange when PKCE data is corrupted', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.setItem(PKCE_STORAGE_KEY, 'not-valid-json{{{')

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: no PKCE verifier found, cannot exchange code')
            expect(global.fetch).not.toHaveBeenCalled()
            warnSpy.mockRestore()
        })

        it('aborts token exchange when no PKCE data exists', async () => {
            const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
            localStorage.removeItem(PKCE_STORAGE_KEY)

            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')

            const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
            logic.mount()

            await expectLogic(logic).delay(0)

            expect(warnSpy).toHaveBeenCalledWith('PostHog Toolbar: no PKCE verifier found, cannot exchange code')
            expect(global.fetch).not.toHaveBeenCalled()
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

        it('returns code and clientId when hash has no server-provided URLs', () => {
            window.history.pushState({}, '', '/#__posthog_toolbar=code:abc,client_id:xyz')
            const result = cleanToolbarAuthHash()
            expect(result).toEqual({ code: 'abc', clientId: 'xyz', redirectUri: undefined, tokenEndpoint: undefined })
            expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/')
        })

        it('parses redirect_uri and token_endpoint from hash', () => {
            const redirectUri = encodeURIComponent('https://internal.example.com/toolbar_oauth/callback')
            const tokenEndpoint = encodeURIComponent('https://internal.example.com/oauth/token/')
            window.history.pushState(
                {},
                '',
                `/#__posthog_toolbar=code:abc,client_id:xyz,redirect_uri:${redirectUri},token_endpoint:${tokenEndpoint}`
            )
            const result = cleanToolbarAuthHash()
            expect(result).toEqual({
                code: 'abc',
                clientId: 'xyz',
                redirectUri: 'https://internal.example.com/toolbar_oauth/callback',
                tokenEndpoint: 'https://internal.example.com/oauth/token/',
            })
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
