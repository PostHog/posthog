import { browserSupportsWebAuthnAutofill, startAuthentication } from '@simplewebauthn/browser'
import { expectLogic } from 'kea-test-utils'

import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@simplewebauthn/browser', () => ({
    startAuthentication: jest.fn(),
    browserSupportsWebAuthnAutofill: jest.fn(),
}))

const SAFARI_UA =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15'
const CHROME_UA =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

function setUserAgent(userAgent: string): void {
    Object.defineProperty(window.navigator, 'userAgent', { value: userAgent, configurable: true })
}

describe('passkeyLogic', () => {
    describe('startConditionalPasskeyLogin (WebKit-only passkey autofill)', () => {
        let logic: ReturnType<typeof passkeyLogic.build>
        let beginHandler: jest.Mock
        const originalUserAgent = window.navigator.userAgent

        beforeEach(() => {
            setUserAgent(SAFARI_UA)
            ;(browserSupportsWebAuthnAutofill as jest.Mock).mockResolvedValue(true)
            // Settle the ceremony as a cancellation so it resolves without a page reload.
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
            setUserAgent(originalUserAgent)
            jest.clearAllMocks()
        })

        it('on WebKit, runs a conditional ceremony with browser autofill and no credential constraint', async () => {
            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).toHaveBeenCalledTimes(1)
            const options = (startAuthentication as jest.Mock).mock.calls[0][0]
            expect(options.useBrowserAutofill).toBe(true)
            // Conditional UI must not constrain credentials — the browser offers all discoverable passkeys.
            expect(options.optionsJSON.allowCredentials).toEqual([])
        })

        it('does nothing on a non-WebKit browser (those use the auto-modal instead)', async () => {
            setUserAgent(CHROME_UA)

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

        it('starts only one ceremony when triggered repeatedly', async () => {
            logic.actions.startConditionalPasskeyLogin()
            logic.actions.startConditionalPasskeyLogin()
            await expectLogic(logic).toFinishAllListeners()

            expect(beginHandler).toHaveBeenCalledTimes(1)
        })
    })
})
