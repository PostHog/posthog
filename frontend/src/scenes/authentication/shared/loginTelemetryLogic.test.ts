import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { login2FALogic } from 'scenes/authentication/login-2fa/login2FALogic'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { passwordResetLogic } from 'scenes/authentication/password-reset/passwordResetLogic'
import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('posthog-js')

// isWebKitBrowser() reads navigator.vendor: "Apple Computer, Inc." on WebKit, "Google Inc." on Chromium.
const WEBKIT_VENDOR = 'Apple Computer, Inc.'
const originalVendor = window.navigator.vendor

function capturedProperties(event: string): Record<string, any> | undefined {
    return (posthog.capture as jest.Mock).mock.calls.find(([name]) => name === event)?.[1]
}

function captureCount(event: string): number {
    return (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event).length
}

describe('loginTelemetryLogic', () => {
    let logic: ReturnType<typeof loginTelemetryLogic.build>
    let login: ReturnType<typeof loginLogic.build>
    let precheckHandler: jest.Mock

    beforeEach(() => {
        // Skip the passkey auto-trigger, which is irrelevant to what these cases assert
        Object.defineProperty(window.navigator, 'vendor', { value: WEBKIT_VENDOR, configurable: true })
        precheckHandler = jest.fn(() => [200, { saml_available: false }])
        useMocks({
            get: {
                '/api/users/@me/': () => [200, {}],
                '/api/login/2fa/passkey/methods/': () => [200, { has_totp: true, has_passkeys: false }],
            },
            post: {
                '/api/login/precheck': precheckHandler,
                '/api/login': () => [401, { code: 'invalid_credentials', detail: 'Invalid email or password.' }],
                '/api/reset/': () => [200, { success: true }],
                '/api/login/code-based-verification': () => [
                    429,
                    { code: 'throttled', detail: 'Request was throttled.' },
                ],
            },
        })
        initKeaTests()
        router.actions.push('/login')
        login = loginLogic()
        login.mount()
        logic = loginTelemetryLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        login.unmount()
        Object.defineProperty(window.navigator, 'vendor', { value: originalVendor, configurable: true })
        jest.clearAllMocks()
    })

    it('reports an attempt and its failure for a rejected password', async () => {
        login.actions.setLoginValues({ email: 'user@example.com', password: 'wrong-password' })
        login.actions.submitLogin()
        await expectLogic(login).toDispatchActions(['setGeneralError'])

        expect(capturedProperties('login attempted')).toMatchObject({ method: 'password' })
        expect(capturedProperties('login failed')).toMatchObject({
            step: 'login',
            error_code: 'invalid_credentials',
        })
    })

    // A throttle and an expired code are different failures. Reporting the rejected response, not the
    // banner text, is what keeps them apart.
    it('reports the reason the verification code was rejected', async () => {
        login.actions.setCodeVerificationValue('code', '123456')
        login.actions.submitCodeVerification()
        await expectLogic(login).toDispatchActions(['submitCodeVerificationFailure']).toFinishAllListeners()

        expect(capturedProperties('login failed')).toMatchObject({ step: 'code', error_code: 'throttled' })
    })

    // Editing the code clears the manual error, which must not read as a second failure.
    it('does not report the clearing of a code error', () => {
        login.actions.setCodeVerificationManualErrors({})

        expect(captureCount('login failed')).toBe(0)
    })

    it('reports the step that rejected a second factor', async () => {
        const twoFA = login2FALogic()
        twoFA.mount()
        twoFA.actions.setGeneralError('2fa_invalid', 'Invalid token')
        await expectLogic(twoFA).toFinishAllListeners()
        twoFA.unmount()

        expect(capturedProperties('login failed')).toMatchObject({ step: '2fa', error_code: '2fa_invalid' })
    })

    it('reports a requested reset email', async () => {
        const reset = passwordResetLogic()
        reset.mount()
        reset.actions.setRequestPasswordResetValue('email', 'user@example.com')
        reset.actions.submitRequestPasswordReset()
        await expectLogic(reset).toDispatchActions(['submitRequestPasswordResetSuccess']).toFinishAllListeners()
        reset.unmount()

        expect(captureCount('password reset requested')).toBe(1)
    })

    // The server redirects a failed SSO sign-in back to /login?error_code=..., and kea-router replays
    // that URL while loginLogic mounts, before this logic exists. That is the case where the person
    // is most stuck, so it must not fall through the gap.
    it('reports an error that loginLogic already held when it mounted', () => {
        logic.unmount()
        login.unmount()
        router.actions.push('/login?error_code=improperly_configured_sso&error_detail=Check+your+SSO+setup')
        login = loginLogic()
        login.mount()
        logic = loginTelemetryLogic()
        logic.mount()

        expect(capturedProperties('login failed')).toMatchObject({
            step: 'login',
            error_code: 'improperly_configured_sso',
        })
        expect(captureCount('login failed')).toBe(1)
    })

    // The passkey prompt opens on its own after the precheck, so its failures are not attempts the
    // person made. A funnel that counts driven attempts has to be able to drop them.
    it('gives a passkey failure its own step', () => {
        login.actions.setGeneralError('passkey_error', 'Passkey login failed')

        expect(capturedProperties('login failed')).toMatchObject({ step: 'passkey' })
    })

    // An error raised while the auth scenes are gone — a failed passkey re-authentication inside the
    // app — must not land in the login funnel.
    it('reports nothing once the auth scene unmounts', () => {
        logic.unmount()
        login.actions.setGeneralError('passkey_error', 'Passkey login failed')
        logic.mount()

        expect(captureCount('login failed')).toBe(0)
    })

    // precheck_failed must distinguish "the precheck ran and failed" from "no current precheck
    // exists" — a pending or stale-email result would otherwise be misattributed to this attempt.
    it.each([
        [
            'no precheck has run',
            async (): Promise<void> => {
                login.actions.setLoginValues({ email: 'user@example.com', password: 'wrong' })
            },
            undefined,
        ],
        [
            'the precheck completed for a different email',
            async (): Promise<void> => {
                login.actions.precheck({ email: 'someone-else@example.com' })
                await expectLogic(login).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
                login.actions.setLoginValues({ email: 'user@example.com', password: 'wrong' })
            },
            undefined,
        ],
        [
            'the precheck failed for the current email',
            async (): Promise<void> => {
                precheckHandler.mockImplementationOnce(() => [429, { detail: 'Request was throttled.' }])
                login.actions.setLoginValues({ email: 'user@example.com', password: 'wrong' })
                login.actions.precheck({ email: 'user@example.com' })
                await expectLogic(login).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            },
            true,
        ],
        [
            'the precheck succeeded for the current email',
            async (): Promise<void> => {
                login.actions.setLoginValues({ email: 'user@example.com', password: 'wrong' })
                login.actions.precheck({ email: 'user@example.com' })
                await expectLogic(login).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            },
            false,
        ],
    ])('reports precheck_failed only for a current precheck: %s', async (_name, setup, expected) => {
        await setup()
        login.actions.setGeneralError('invalid_credentials', 'Invalid email or password.')
        await expectLogic(login).toDispatchActions(['setGeneralError']).toFinishAllListeners()

        expect(capturedProperties('login failed')?.precheck_failed).toBe(expected)
    })
})
