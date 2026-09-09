import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
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

    // Kea mounts this logic alongside the telemetry logic these pages use, so the guard is that a
    // mount alone asks nothing. The server rejects the question outside a pending 2FA session.
    it.each([
        ['the login page', urls.login()],
        ['the password reset page', urls.passwordReset()],
    ])('does not ask which 2FA methods exist on %s', async (_name, url) => {
        router.actions.push(url)
        loginTelemetryLogic().mount()

        await expectLogic(login2FALogic).toFinishAllListeners()

        expect(methodsHandler).not.toHaveBeenCalled()
    })

    it('asks again on every arrival at the 2FA step, so a passkey stays offered', async () => {
        router.actions.push(urls.login())
        loginTelemetryLogic().mount()

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
