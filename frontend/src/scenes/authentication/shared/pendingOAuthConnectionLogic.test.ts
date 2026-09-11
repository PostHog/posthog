import { setPendingOAuthConnectionCookie as setCookie } from './pendingOAuthConnection.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { pendingOAuthConnectionLogic, readPendingOAuthConnection } from './pendingOAuthConnectionLogic'

jest.mock('posthog-js')

const CLIENT_ID = 'https://claude.example.com/.well-known/oauth-client'

function encoded(payload: unknown): string {
    return encodeURIComponent(JSON.stringify(payload))
}

describe('pendingOAuthConnectionLogic', () => {
    beforeEach(() => {
        initKeaTests()
        setCookie(null)
        jest.mocked(posthog.capture).mockClear()
    })

    it('reads the cookie the authorize endpoint set and reports which screen showed it', async () => {
        setCookie({
            client_name: 'Claude &amp; Co',
            client_id: CLIENT_ID,
            logo_uri: 'https://claude.example.com/logo.png',
            redirect_host: 'claude.example.com',
        })
        router.actions.push('/login')
        const logic = pendingOAuthConnectionLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            pendingConnection: {
                clientName: 'Claude & Co',
                clientId: CLIENT_ID,
                logoUri: 'https://claude.example.com/logo.png',
                redirectHost: 'claude.example.com',
            },
        })
        expect(posthog.capture).toHaveBeenCalledTimes(1)
        expect(posthog.capture).toHaveBeenCalledWith('oauth pending connection viewed', {
            screen: 'login',
            client_name: 'Claude & Co',
            client_id: CLIENT_ID,
        })
    })

    it('reports nothing when no connection is pending', async () => {
        router.actions.push('/signup')
        const logic = pendingOAuthConnectionLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ pendingConnection: null })
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('reports nothing from a screen outside the auth flow', async () => {
        setCookie({ client_name: 'Claude', client_id: CLIENT_ID })
        router.actions.push('/organization/confirm-creation')
        const logic = pendingOAuthConnectionLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            pendingConnection: expect.objectContaining({ clientName: 'Claude' }),
        })
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it.each([
        ['not JSON', 'nope'],
        ['not an object', encoded([])],
        ['missing client_id', encoded({ client_name: 'Claude' })],
        ['empty client_name', encoded({ client_name: '', client_id: CLIENT_ID })],
    ])('treats a cookie that is %s as no pending connection', (_name, raw) => {
        setCookie(raw)

        expect(readPendingOAuthConnection()).toBeNull()
    })

    it('keeps the connection but drops a logo that is not an https URL', () => {
        setCookie(encoded({ client_name: 'Cursor', client_id: 'cursor', logo_uri: 'data:image/png;base64,AAAA' }))

        expect(readPendingOAuthConnection()).toEqual({
            clientName: 'Cursor',
            clientId: 'cursor',
            logoUri: null,
            redirectHost: null,
        })
    })
})
