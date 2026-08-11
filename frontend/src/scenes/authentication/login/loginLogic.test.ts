import { startAuthentication } from '@simplewebauthn/browser'
import { router } from 'kea-router'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'
import posthog from 'posthog-js'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { handleLoginRedirect, loginLogic } from 'scenes/authentication/login/loginLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'

import { initKea } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('@simplewebauthn/browser', () => ({ startAuthentication: jest.fn() }))
jest.mock('posthog-js')

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
            // Percent-encoded chars nested in next's own query params must survive the redirect
            // (e.g. docs "Run in PostHog" links carrying %0A newlines in open_query); the router
            // round-trip normalizes form-encoded "+" spaces to "%20", which decodes the same
            [
                '/sql?open_query=SELECT%0A++properties.%24mcp+AS+tool',
                '/sql?open_query=SELECT%0A%20%20properties.%24mcp%20AS%20tool',
            ],
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

    describe('opaque login failure', () => {
        let logic: ReturnType<typeof loginLogic.build>
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR) // skip passkey auto-trigger
            useMocks({
                get: { '/api/users/@me/': () => [200, {}] },
                post: {
                    '/api/login/precheck': () => [200, { saml_available: false }],
                    // A response with no JSON body (a 5xx from the edge, a dropped connection) leaves
                    // `code`/`detail` null on the resulting ApiError.
                    '/api/login': () => [502],
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

        it('reports the underlying status when code and detail are both null', async () => {
            logic.actions.setLoginValues({ email: 'user@example.com', password: 'a-password' })
            logic.actions.submitLogin()
            await expectLogic(logic).toDispatchActions(['submitLoginFailure'])

            expect(logic.values.generalError?.code).toBeFalsy()
            expect(posthog.captureException).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({ extra: expect.objectContaining({ status: 502 }) })
            )
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

        it('retries a failed precheck instead of caching its fallback for the page session', async () => {
            precheckHandler.mockImplementationOnce(() => [429, { detail: 'Request was throttled.' }])

            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            // The fallback keeps the form usable, but doesn't know about this account's real options.
            expect(logic.values.precheckResponse).toMatchObject({ status: 'completed', precheckFailed: true })
            expect(logic.values.precheckResponse.sso_enforcement).toBeUndefined()

            precheckHandler.mockImplementationOnce(() => [
                200,
                { saml_available: false, sso_enforcement: 'google-oauth2' },
            ])
            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            expect(precheckHandler).toHaveBeenCalledTimes(2)
            expect(logic.values.precheckResponse.sso_enforcement).toEqual('google-oauth2')
        })
    })

    describe('available login methods', () => {
        let logic: ReturnType<typeof loginLogic.build>
        let precheckResponse: Record<string, any>
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR) // skip the passkey auto-trigger, isolate the precheck response
            precheckResponse = { saml_available: false }
            useMocks({ post: { '/api/login/precheck': () => [200, precheckResponse] } })
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

        async function precheck(response: Record<string, any>): Promise<void> {
            precheckResponse = response
            logic.actions.precheck({ email: 'user@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
        }

        it('keeps password login available before precheck resolves', () => {
            expect(logic.values.isPasswordLoginUnavailable).toBe(false)
            expect(logic.values.availableLoginMethods).toEqual([])
            expect(logic.values.restrictToProviders).toBe(null)
        })

        it('keeps password login available for a response without the field', async () => {
            // A server that predates this field must not make the password box disappear.
            await precheck({ saml_available: false })
            expect(logic.values.isPasswordLoginUnavailable).toBe(false)
            expect(logic.values.availableLoginMethods).toEqual(['password'])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(false)
            expect(logic.values.restrictToProviders).toBe(null)
        })

        it('keeps password login available for an unknown email', async () => {
            await precheck({ saml_available: false, password_login_available: true, social_providers: [] })
            expect(logic.values.isPasswordLoginUnavailable).toBe(false)
            expect(logic.values.availableLoginMethods).toEqual(['password'])
        })

        it('offers only the linked provider for a passwordless account', async () => {
            await precheck({
                saml_available: false,
                password_login_available: false,
                social_providers: ['google-oauth2'],
            })
            expect(logic.values.isPasswordLoginUnavailable).toBe(true)
            expect(logic.values.availableLoginMethods).toEqual(['google-oauth2'])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(false)
            expect(logic.values.restrictToProviders).toEqual(['google-oauth2'])
        })

        it('offers only the passkey for a passwordless account with one', async () => {
            await precheck({
                saml_available: false,
                password_login_available: false,
                social_providers: [],
                webauthn_credentials: [{ id: 'cred-1', type: 'public-key' }],
            })
            expect(logic.values.availableLoginMethods).toEqual(['passkey'])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(false)
            expect(logic.values.restrictToProviders).toEqual([])
        })

        it('offers SAML for a passwordless account on a SAML domain', async () => {
            await precheck({ saml_available: true, password_login_available: false, social_providers: [] })
            expect(logic.values.availableLoginMethods).toEqual(['saml'])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(false)
        })

        it('reports a dead end for a passwordless account with nothing else', async () => {
            await precheck({ saml_available: false, password_login_available: false, social_providers: [] })
            expect(logic.values.isPasswordLoginUnavailable).toBe(true)
            expect(logic.values.availableLoginMethods).toEqual([])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(true)
        })

        it('defers entirely to enforced SSO', async () => {
            await precheck({
                saml_available: false,
                sso_enforcement: 'google-oauth2',
                password_login_available: false,
                social_providers: [],
            })
            expect(logic.values.availableLoginMethods).toEqual([])
            expect(logic.values.hasNoConfiguredLoginMethod).toBe(false)
        })

        it('falls back to password login when precheck fails, so a 429 cannot lock the form', async () => {
            useMocks({ post: { '/api/login/precheck': () => [429, { detail: 'Request was throttled.' }] } })
            logic.actions.precheck({ email: 'user@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()

            expect(logic.values.precheckResponse.status).toBe('completed')
            expect(logic.values.isPasswordLoginUnavailable).toBe(false)
            expect(logic.values.availableLoginMethods).toEqual(['password'])
        })
    })

    describe('auto-redirect to a single login method', () => {
        let logic: ReturnType<typeof loginLogic.build>
        let precheckResponse: Record<string, any>
        let assignMock: jest.Mock
        const originalVendor = window.navigator.vendor

        beforeEach(() => {
            setVendor(WEBKIT_VENDOR) // skip the passkey auto-trigger, isolate the redirect
            precheckResponse = {
                saml_available: false,
                password_login_available: false,
                social_providers: ['google-oauth2'],
            }
            useMocks({ post: { '/api/login/precheck': () => [200, precheckResponse] } })
            initKeaTests()
            router.actions.push('/login')
            logic = loginLogic()
            logic.mount()
            assignMock = jest.fn()
            Object.defineProperty(window, 'location', {
                value: { ...window.location, assign: assignMock },
                configurable: true,
            })
        })

        afterEach(() => {
            logic.unmount()
            setVendor(originalVendor)
            jest.clearAllMocks()
        })

        it('redirects when the account has exactly one method and the user explicitly submitted the email', async () => {
            logic.actions.setLoginValue('email', 'user@example.com')
            logic.actions.precheck({ email: 'user@example.com', autoAttempt: true })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()

            expect(logic.values.autoRedirectingToProvider).toBe('google-oauth2')
            expect(assignMock).toHaveBeenCalledWith('/login/google-oauth2/?email=user%40example.com')
        })

        it('does not redirect without autoAttempt, so autofill and ?email= links stay put', async () => {
            logic.actions.setLoginValue('email', 'user@example.com')
            logic.actions.precheck({ email: 'user@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()

            expect(logic.values.autoRedirectingToProvider).toBe(null)
            expect(assignMock).not.toHaveBeenCalled()
        })

        it('does not redirect when the account has more than one method', async () => {
            precheckResponse = {
                saml_available: false,
                password_login_available: false,
                social_providers: ['google-oauth2'],
                webauthn_credentials: [{ id: 'cred-1', type: 'public-key' }],
            }
            logic.actions.setLoginValue('email', 'user@example.com')
            logic.actions.precheck({ email: 'user@example.com', autoAttempt: true })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()

            expect(assignMock).not.toHaveBeenCalled()
        })

        it('does not redirect when the account can use a password', async () => {
            precheckResponse = { saml_available: false, password_login_available: true, social_providers: [] }
            logic.actions.setLoginValue('email', 'user@example.com')
            logic.actions.precheck({ email: 'user@example.com', autoAttempt: true })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()

            expect(assignMock).not.toHaveBeenCalled()
        })

        it('redirects at most once per email', async () => {
            logic.actions.setLoginValue('email', 'user@example.com')
            logic.actions.precheck({ email: 'user@example.com', autoAttempt: true })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            expect(assignMock).toHaveBeenCalledTimes(1)

            logic.actions.precheck({ email: 'user@example.com', autoAttempt: true })
            await expectLogic(logic).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            expect(assignMock).toHaveBeenCalledTimes(1)
        })
    })

    describe('cross-project redirect after login', () => {
        const originalContext = window.POSTHOG_APP_CONTEXT
        const originalLocation = window.location
        let hrefSpy: jest.Mock

        beforeEach(() => {
            initKeaTests()
            // getCurrentTeamIdOrNone() reads the current project from the app context.
            window.POSTHOG_APP_CONTEXT = { current_team: { id: 5 } } as any
            hrefSpy = jest.fn()
            Object.defineProperty(window, 'location', {
                value: {
                    origin: 'http://localhost',
                    pathname: '/login',
                    search: '',
                    hash: '',
                    set href(url: string) {
                        hrefSpy(url)
                    },
                },
                configurable: true,
            })
        })

        afterEach(() => {
            window.POSTHOG_APP_CONTEXT = originalContext
            Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        })

        it('does a full navigation to a project other than the current one', () => {
            router.actions.push(`/login?next=${encodeURIComponent('/project/999/pipeline/destinations/hog-abc')}`)
            handleLoginRedirect()
            // A full load lets AutoProjectMiddleware switch the active project before the scene mounts.
            expect(hrefSpy).toHaveBeenCalledWith('/project/999/pipeline/destinations/hog-abc')
        })

        it('stays client-side when the target is already the current project', () => {
            router.actions.push(`/login?next=${encodeURIComponent('/project/5/pipeline/destinations/hog-abc')}`)
            handleLoginRedirect()
            expect(hrefSpy).not.toHaveBeenCalled()
        })

        it('does a full navigation for a project token the middleware resolves server-side', () => {
            // A `phc_` key or a legacy allowlisted api_token can't be compared to the numeric team id,
            // so it must reach AutoProjectMiddleware for resolution — client-side routing wouldn't switch.
            router.actions.push(`/login?next=${encodeURIComponent('/project/phc_ABC123/pipeline/destinations')}`)
            handleLoginRedirect()
            expect(hrefSpy).toHaveBeenCalledWith('/project/phc_ABC123/pipeline/destinations')
        })
    })
})
