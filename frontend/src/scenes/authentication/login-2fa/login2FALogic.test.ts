import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { login2FALogic } from './login2FALogic'

describe('login2FALogic', () => {
    let methodsHandler: jest.Mock

    beforeEach(() => {
        methodsHandler = jest.fn(() => [200, { has_totp: false, has_passkeys: true }])
        useMocks({ get: { '/api/login/2fa/passkey/methods/': methodsHandler } })
        initKeaTests()
    })

    // Kea mounts this logic alongside anything that references its actions, which can happen on any
    // page, so a mount alone must ask nothing. The server rejects the question outside a pending 2FA
    // session.
    it.each([
        ['the login page', urls.login()],
        ['the password reset page', urls.passwordReset()],
    ])('does not ask which 2FA methods exist on %s', async (_name, url) => {
        router.actions.push(url)
        login2FALogic().mount()

        await expectLogic(login2FALogic).toFinishAllListeners()

        expect(methodsHandler).not.toHaveBeenCalled()
    })

    // A refresh or a hard load lands on the route before this logic exists, so the request has to
    // follow the current URL and not only a navigation to it.
    it('asks when it mounts on the 2FA step, so a refresh still offers a passkey', async () => {
        router.actions.push(urls.login2FA())
        login2FALogic().mount()

        await expectLogic(login2FALogic).toFinishAllListeners()

        expect(methodsHandler).toHaveBeenCalledTimes(1)
        await expectLogic(login2FALogic).toMatchValues({ passkeysAvailable: true })
    })

    it('asks again on every arrival at the 2FA step, so a passkey stays offered', async () => {
        router.actions.push(urls.login())
        login2FALogic().mount()

        router.actions.push(urls.login2FA())
        await expectLogic(login2FALogic).toFinishAllListeners()
        expect(methodsHandler).toHaveBeenCalledTimes(1)
        await expectLogic(login2FALogic).toMatchValues({ passkeysAvailable: true })

        router.actions.push(urls.login())
        router.actions.push(urls.login2FA())
        await expectLogic(login2FALogic).toFinishAllListeners()
        expect(methodsHandler).toHaveBeenCalledTimes(2)
    })
})
