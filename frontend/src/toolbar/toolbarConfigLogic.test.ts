import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

describe('toolbar toolbarConfigLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('is not authenticated without any token', () => {
        const logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
        logic.mount()
        expectLogic(logic).toMatchValues({ isAuthenticated: false })
    })

    it('is authenticated with temporaryToken', () => {
        const logic = toolbarConfigLogic.build({
            apiURL: 'http://localhost',
            temporaryToken: 'temp-token-123',
        })
        logic.mount()
        expectLogic(logic).toMatchValues({ isAuthenticated: true })
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
            logic.actions.setOAuthTokens('pha_new', 'phr_new', 3600, 'client-123')
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
})
