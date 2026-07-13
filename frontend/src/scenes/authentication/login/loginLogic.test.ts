import { startAuthentication } from '@simplewebauthn/browser'
import { router } from 'kea-router'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { handleLoginRedirect, loginLogic } from 'scenes/authentication/login/loginLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { initKea } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@simplewebauthn/browser', () => ({ startAuthentication: jest.fn() }))

// isWebKitBrowser() reads navigator.vendor: "Apple Computer, Inc." on WebKit, "Google Inc." on Chromium.
const WEBKIT_VENDOR = 'Apple Computer, Inc.'
const CHROMIUM_VENDOR = 'Google Inc.'

function setVendor(vendor: string): void {
    Object.defineProperty(window.navigator, 'vendor', { value: vendor, configurable: true })
}

describe('loginLogic', () => {
    describe('redirect vulnerability', () => {
        beforeEach(() => {
            // Note, initKeaTests() is not called here because that uses a memory history, which doesn't throw on origin redirect
            initKea({ beforePlugins: [testUtilsPlugin] })
        })
        it('should ignore redirect attempt to a different origin', () => {
            router.actions.push(`${origin}/login?next=//google.com`)
            handleLoginRedirect()
            expect(router.values.location.pathname).toEqual('/')
        })
    })

    describe('wasSignedOutForSessionRisk', () => {
        let logic: ReturnType<typeof loginLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = loginLogic()
            logic.mount()
        })

        const cases: [string, boolean][] = [
            ['/login?reason=session_risk', true],
            ['/login?reason=something_else', false],
            ['/login', false],
        ]

        for (const [url, expected] of cases) {
            it(`for "${url}" it returns ${expected}`, () => {
                router.actions.push(url)
                expect(logic.values.wasSignedOutForSessionRisk).toEqual(expected)
            })
        }
    })

    describe('parseLoginRedirectURL', () => {
        let logic: ReturnType<typeof loginLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = loginLogic()
            logic.mount()
        })

        const origin = `http://localhost`
        const matches = [
            [null, '/'],
            ['/', '/'],
            ['asdf', '/'],
            ['?next=javascript:something', '/'],
            ['javascript:something', '/'],
            ['/bla', '/bla'],
            [`${origin}/bla`, '/bla'],
            [`http://some-other.origin/bla`, '/'],
            ['//foo.bar', '/'],
            ['/bla?haha', '/bla?haha'],
            ['/bla?haha#hoho', '/bla?haha#hoho'],
        ]

        for (const [next, result] of matches) {
            it(`for next param "${next}" it returns "${result}"`, () => {
                if (next) {
                    const [nextPath, nextHash] = next.split('#')
                    // The hash is the only part of the URL that isn't sent to the server
                    router.actions.push(
                        `${origin}/?next=${encodeURIComponent(nextPath)}${nextHash ? `#` + nextHash : ''}`
                    )
                } else {
                    router.actions.push(origin)
                }
                handleLoginRedirect()
                const newPath =
                    router.values.location.pathname + router.values.location.search + router.values.location.hash
                expect(removeProjectIdIfPresent(newPath)).toEqual(result)
            })
        }
    })

    describe('passkey auto-trigger after precheck', () => {
        let logic: ReturnType<typeof loginLogic.build>
        let beginHandler: jest.Mock
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(CHROMIUM_VENDOR)
            // Treat the passkey prompt as a user cancellation so it resolves without a page reload.
            ;(startAuthentication as jest.Mock).mockRejectedValue(
                Object.assign(new Error('cancelled'), { name: 'AbortError' })
            )
            beginHandler = jest.fn(() => [
                200,
                {
                    challenge: 'abc',
                    timeout: 60000,
                    rpId: 'localhost',
                    allowCredentials: [],
                    userVerification: 'preferred',
                },
            ])
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: {
                    '/api/login/precheck': () => [
                        200,
                        { saml_available: false, webauthn_credentials: [{ id: 'cred-1', type: 'public-key' }] },
                    ],
                    '/api/webauthn/login/begin/': beginHandler,
                },
            })
            initKeaTests()
            router.actions.push('/login')
            logic = loginLogic()
            logic.mount()
            passkeyLogic().mount()
        })

        afterEach(() => {
            passkeyLogic().unmount()
            logic.unmount()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('auto-triggers the passkey prompt on non-WebKit browsers', async () => {
            logic.actions.precheck({ email: 'user@example.com' })
            // Drain the whole passkey flow (begin request included) so nothing leaks into the next test.
            await expectLogic(passkeyLogic)
                .toDispatchActions(['beginPasskeyLogin', 'startPasskeyAuthenticationSuccess'])
                .toFinishAllListeners()
            expect(beginHandler).toHaveBeenCalledTimes(1)
        })

        it('does not auto-trigger the passkey modal on WebKit (Safari)', async () => {
            setVendor(WEBKIT_VENDOR)
            logic.actions.precheck({ email: 'user@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            expect(beginHandler).not.toHaveBeenCalled()
        })
    })

    describe('code-based verification', () => {
        let logic: ReturnType<typeof loginLogic.build>
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR) // skip passkey auto-trigger
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: {
                    '/api/login/precheck': () => [200, { saml_available: false }],
                    '/api/login': () => [401, { code: 'code_based_verification_required', detail: 'user@example.com' }],
                    '/api/login/code-based-verification': () => [200, { success: true }],
                },
            })
            initKeaTests()
            router.actions.push('/login')
            logic = loginLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('enters code-entry mode when login requires a code, and exits on demand', async () => {
            logic.actions.setLoginValues({ email: 'user@example.com', password: 'a-password' })
            logic.actions.submitLogin()
            await expectLogic(logic).toDispatchActions(['setCodeVerificationRequired', 'submitLoginFailure'])

            expect(logic.values.codeVerificationRequired).toBe(true)
            expect(logic.values.generalError?.code).toBe('code_based_verification_sent')

            logic.actions.exitCodeVerification()
            expect(logic.values.codeVerificationRequired).toBe(false)
            expect(logic.values.generalError).toBe(null)
        })
    })

    describe('precheck dedupe', () => {
        let logic: ReturnType<typeof loginLogic.build>
        let precheckHandler: jest.Mock
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR) // skip passkey auto-trigger, isolate precheck
            precheckHandler = jest.fn(() => [200, { saml_available: false }])
            useMocks({ post: { '/api/login/precheck': precheckHandler } })
            initKeaTests()
            router.actions.push('/login')
            logic = loginLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('skips a redundant precheck for an already-resolved email but re-runs for a new one', async () => {
            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            expect(precheckHandler).toHaveBeenCalledTimes(1)

            logic.actions.precheck({ email: 'b@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            expect(precheckHandler).toHaveBeenCalledTimes(2)
        })
    })
})
