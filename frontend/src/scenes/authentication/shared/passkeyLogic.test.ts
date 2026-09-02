import { browserSupportsWebAuthnAutofill, startAuthentication } from '@simplewebauthn/browser'
import { expectLogic } from 'kea-test-utils'

import { loginLogic } from 'scenes/authentication/login/loginLogic'
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

    describe('beginPasskeyLogin (authenticator failure)', () => {
        let logic: ReturnType<typeof passkeyLogic.build>

        beforeEach(() => {
            ;(startAuthentication as jest.Mock).mockRejectedValue(
                new DOMException('The operation failed for an operation-specific reason', 'OperationError')
            )
            useMocks({
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
                },
            })
            initKeaTests()
            loginLogic.mount()
            logic = passkeyLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            jest.clearAllMocks()
        })

        it('shows a friendly message and does not report the authenticator DOMException as a failure', async () => {
            logic.actions.beginPasskeyLogin()

            // The DOMException must not reach the loader failure path, which is where it would be
            // captured as a fatal exception the user cannot act on.
            await expectLogic(logic)
                .toDispatchActions([
                    loginLogic.actionCreators.setGeneralError(
                        'passkey_error',
                        'Your device could not complete the passkey. Please try again, or use your password.'
                    ),
                    'passkeyAuthenticationFailed',
                    'startPasskeyAuthenticationSuccess',
                ])
                .toNotHaveDispatchedActions(['startPasskeyAuthenticationFailure'])
        })

        it('rethrows a non-OperationError DOMException so it stays reportable', async () => {
            // A NotSupportedError signals a browser or configuration defect, not an OperationError the
            // user must simply retry. It must reach the loader failure path, which is where the global
            // reporter captures it, rather than be swallowed like OperationError.
            ;(startAuthentication as jest.Mock).mockRejectedValue(
                new DOMException('The requested operation is not supported', 'NotSupportedError')
            )

            logic.actions.beginPasskeyLogin()

            await expectLogic(logic)
                .toDispatchActions(['startPasskeyAuthenticationFailure'])
                .toNotHaveDispatchedActions(['passkeyAuthenticationFailed'])
        })
    })
})
