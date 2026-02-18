import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { OAUTH_LOCALSTORAGE_KEY } from '~/toolbar/utils'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

describe('toolbar toolbarConfigLogic', () => {
    let mockOpen: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
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

    it('setOAuthTokens updates tokens and clears temporaryToken', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            temporaryToken: 'temp-123',
        })
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.setOAuthTokens('pha_new', 'phr_new', 'client-123')
        }).toMatchValues({
            accessToken: 'pha_new',
            refreshToken: 'phr_new',
            clientId: 'client-123',
            temporaryToken: null,
            isAuthenticated: true,
        })
    })

    it('logout clears all tokens', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            temporaryToken: 'temp',
            accessToken: 'access',
            refreshToken: 'refresh',
            clientId: 'client',
        })
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.logout()
        }).toMatchValues({
            temporaryToken: null,
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
            posthog: { config: { ui_host: 'https://us.posthog.com/' } } as any,
        } as any)
        logic.mount()
        expect(logic.values.uiHost.endsWith('/')).toBe(false)
        expect(logic.values.uiHost).toBe('https://us.posthog.com')
    })

    describe('OAuth migration', () => {
        it('auto-opens OAuth popup when temporaryToken exists without stored OAuth', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                temporaryToken: 'temp-token-123',
            })
            logic.mount()

            expect(mockOpen).toHaveBeenCalledWith(
                expect.stringContaining('/toolbar_oauth/authorize/'),
                'posthog_toolbar_oauth',
                'width=600,height=700'
            )
            // Temp token stays active so toolbar remains functional during popup
            expectLogic(logic).toMatchValues({ temporaryToken: 'temp-token-123', isAuthenticated: true })
        })

        it('restores OAuth from localStorage instead of migrating (old bookmark with temp token)', () => {
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
                temporaryToken: 'old-temp-token',
            })
            logic.mount()

            // OAuth popup should NOT open — stored tokens are sufficient
            expect(mockOpen).not.toHaveBeenCalled()
            expectLogic(logic).toMatchValues({
                accessToken: 'stored-access',
                refreshToken: 'stored-refresh',
                clientId: 'stored-client',
                temporaryToken: null,
                isAuthenticated: true,
            })
        })

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

        it('does not migrate when accessToken already exists in props', () => {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'existing-access',
                refreshToken: 'existing-refresh',
                clientId: 'existing-client',
            })
            logic.mount()

            expect(mockOpen).not.toHaveBeenCalled()
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
})
