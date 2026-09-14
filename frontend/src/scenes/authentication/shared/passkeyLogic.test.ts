import { browserSupportsWebAuthnAutofill, startAuthentication } from '@simplewebauthn/browser'
import { expectLogic } from 'kea-test-utils'

import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@simplewebauthn/browser', () => ({
    startAuthentication: jest.fn(),
    browserSupportsWebAuthnAutofill: jest.fn(),
}))

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

    describe('re-authentication', () => {
        let logic: ReturnType<typeof passkeyLogic.build>

        beforeEach(() => {
            ;(startAuthentication as jest.Mock).mockResolvedValue({ id: 'cred-1', response: {} })
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: {
                    '/api/webauthn/login/begin/': () => [
                        200,
                        {
                            challenge: 'abc',
                            timeout: 60000,
                            rpId: 'localhost',
                            allowCredentials: [{ id: 'cred-1', type: 'public-key' }],
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
            jest.clearAllMocks()
        })

        it('signals the sensitive action waiting on re-authentication', async () => {
            const onSuccess = jest.fn()
            const onFailure = jest.fn()
            // A sensitive action (e.g. inviting members) parks this pair while it awaits re-auth.
            // Without the signal it stays pending forever and its button spins.
            apiStatusLogic.actions.setTimeSensitiveAuthenticationRequired([onSuccess, onFailure])

            logic.actions.beginPasskeyLogin(undefined, { reauth: 'true' })
            await expectLogic(logic).toFinishAllListeners()

            expect(onSuccess).toHaveBeenCalledTimes(1)
            expect(onFailure).not.toHaveBeenCalled()
            expect(apiStatusLogic.values.timeSensitiveAuthenticationRequired).toBe(false)
        })
    })
})
