import { browserSupportsWebAuthnAutofill, startAuthentication } from '@simplewebauthn/browser'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { PASSKEY_LOGIN_TIMEOUT_MS, passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@simplewebauthn/browser', () => ({
    startAuthentication: jest.fn(),
    browserSupportsWebAuthnAutofill: jest.fn(),
    WebAuthnAbortService: { cancelCeremony: jest.fn() },
}))
jest.mock('posthog-js')

// isWebKitBrowser() reads navigator.vendor: "Apple Computer, Inc." on WebKit, "Google Inc." on Chromium.
const WEBKIT_VENDOR = 'Apple Computer, Inc.'
const CHROMIUM_VENDOR = 'Google Inc.'

function setVendor(vendor: string): void {
    Object.defineProperty(window.navigator, 'vendor', { value: vendor, configurable: true })
}

describe('passkeyLogic', () => {
    describe('startConditionalPasskeyLogin (WebKit-only passkey autofill)', () => {
        let logic: ReturnType<typeof passkeyLogic.build>
        let beginHandler: jest.Mock
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR)
            ;(browserSupportsWebAuthnAutofill as jest.Mock).mockResolvedValue(true)
            // Resolve the passkey prompt as a cancellation so it settles without a page reload.
            ;(startAuthentication as jest.Mock).mockRejectedValue(
                Object.assign(new Error('cancelled'), { name: 'AbortError' })
            )
            beginHandler = jest.fn(() => [
                200,
                {
                    challenge: 'abc',
                    timeout: 60000,
                    rpId: 'localhost',
                    allowCredentials: [{ id: 'cred-1', type: 'public-key' }],
                    userVerification: 'required',
                },
            ])
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: { '/api/webauthn/login/begin/': beginHandler },
            })
            initKeaTests()
            logic = passkeyLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('on WebKit, requests a passkey via browser autofill with no credential constraint', async () => {
            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).toHaveBeenCalledTimes(1)
            const options = (startAuthentication as jest.Mock).mock.calls[0][0]
            expect(options.useBrowserAutofill).toBe(true)
            // Conditional UI must not constrain credentials — the browser offers all discoverable passkeys.
            expect(options.optionsJSON.allowCredentials).toEqual([])
        })

        it('does nothing on a non-WebKit browser (those use the auto-modal instead)', async () => {
            setVendor(CHROMIUM_VENDOR)

            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).not.toHaveBeenCalled()
            expect(startAuthentication).not.toHaveBeenCalled()
        })

        it('does nothing when the browser does not support autofill', async () => {
            ;(browserSupportsWebAuthnAutofill as jest.Mock).mockResolvedValue(false)

            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).not.toHaveBeenCalled()
            expect(startAuthentication).not.toHaveBeenCalled()
        })

        it('starts only one passkey request when triggered repeatedly', async () => {
            logic.actions.startConditionalPasskeyLogin()
            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).toHaveBeenCalledTimes(1)
        })
    })

    describe('startPasskeyAuthentication (the passkey button prompt)', () => {
        let logic: ReturnType<typeof passkeyLogic.build>
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(CHROMIUM_VENDOR)
            jest.useFakeTimers()
            // A ceremony that never settles is the stuck sign-in this suite is about.
            ;(startAuthentication as jest.Mock).mockImplementation(() => new Promise(() => {}))
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: {
                    '/api/webauthn/login/begin/': () => [
                        200,
                        {
                            challenge: 'abc',
                            timeout: 60000,
                            rpId: 'localhost',
                            allowCredentials: [],
                            userVerification: 'required',
                        },
                    ],
                    '/api/webauthn/login/complete/': () => [200, {}],
                },
            })
            initKeaTests()
            logic = passkeyLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            jest.useRealTimers()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('stops the spinner and shows an error when the passkey never answers', async () => {
            logic.actions.beginPasskeyLogin()
            await jest.advanceTimersByTimeAsync(PASSKEY_LOGIN_TIMEOUT_MS + 1000)

            expect(logic.values.isLoading).toBe(false)
            expect(loginLogic.values.generalError?.code).toBe('passkey_error')
            expect(posthog.capture).toHaveBeenCalledWith(
                'passkey login timed out',
                expect.objectContaining({ method: 'prompt' })
            )
        })

        it('stops the spinner when the user cancels the attempt', async () => {
            logic.actions.beginPasskeyLogin()
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.cancelPasskeyLogin()
            await jest.advanceTimersByTimeAsync(0)

            expect(logic.values.isLoading).toBe(false)
            expect(loginLogic.values.generalError).toBeFalsy()
        })

        it('starts a new attempt when a request repeats while one is in flight', async () => {
            logic.actions.beginPasskeyLogin()
            await jest.advanceTimersByTimeAsync(0)
            expect(startAuthentication).toHaveBeenCalledTimes(1)

            logic.actions.beginPasskeyLogin()
            await jest.advanceTimersByTimeAsync(1000)

            expect(startAuthentication).toHaveBeenCalledTimes(2)
            expect(logic.values.isLoading).toBe(true)
        })
    })
})
