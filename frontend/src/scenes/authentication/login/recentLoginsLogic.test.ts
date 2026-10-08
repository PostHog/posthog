import { setLastLoginMethodCookie } from 'scenes/authentication/shared/lastLoginMethod.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { recentLoginsLogic } from 'scenes/authentication/login/recentLoginsLogic'
import { readRecentLogins, recordRecentLogin } from 'scenes/authentication/shared/recentLogins'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { LoginMethod } from '~/types'

jest.mock('posthog-js')

const WEBKIT_VENDOR = 'Apple Computer, Inc.'

function record(email: string, method: LoginMethod, isImpersonated = false): void {
    setLastLoginMethodCookie(method)
    recordRecentLogin({ email, is_impersonated: isImpersonated })
}

describe('recentLoginsLogic', () => {
    const originalLocation = window.location
    const originalVendor = window.navigator.vendor
    let assignMock: jest.Mock
    let precheckResponse: Record<string, unknown>
    let precheckStatus: number

    beforeEach(() => {
        Object.defineProperty(window.navigator, 'vendor', { value: WEBKIT_VENDOR, configurable: true }) // skip passkey auto-trigger
        precheckResponse = { saml_available: false }
        precheckStatus = 200
        useMocks({ post: { '/api/login/precheck': () => [precheckStatus, precheckResponse] } })
        initKeaTests()
        router.actions.push('/login')
        // initKeaTests loads a mock user, and userLogic records that user
        window.localStorage.clear()
        assignMock = jest.fn()
        Object.defineProperty(window, 'location', {
            value: { ...originalLocation, assign: assignMock },
            configurable: true,
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        Object.defineProperty(window.navigator, 'vendor', { value: originalVendor, configurable: true })
        setLastLoginMethodCookie(null)
    })

    it('keeps the three newest accounts, one row per address', () => {
        const recorded = (): [string, LoginMethod][] => readRecentLogins().map(({ email, method }) => [email, method])

        record('a@example.com', 'password')
        record('b@example.com', 'google-oauth2')
        record('A@Example.com', 'passkey')
        expect(recorded()).toEqual([
            ['A@Example.com', 'passkey'],
            ['b@example.com', 'google-oauth2'],
        ])

        record('c@example.com', 'saml')
        record('d@example.com', 'github')
        expect(recorded()).toEqual([
            ['d@example.com', 'github'],
            ['c@example.com', 'saml'],
            ['A@Example.com', 'passkey'],
        ])
    })

    it('records nothing for an impersonated session', () => {
        record('customer@example.com', 'saml', true)

        expect(readRecentLogins()).toEqual([])
    })

    function mountLogin(url: string, hasRows: boolean): ReturnType<typeof loginLogic.build> {
        if (hasRows) {
            record('user@example.com', 'password')
        }
        router.actions.push(url)
        const login = loginLogic()
        login.mount()
        recentLoginsLogic.mount()
        return login
    }

    function selectRow(method: LoginMethod): ReturnType<typeof loginLogic.build> {
        const login = mountLogin('/login', true)
        recentLoginsLogic.actions.selectRecentLogin({
            email: 'user@example.com',
            method,
            lastUsedAt: '2026-10-01T10:00:00Z',
        })
        return login
    }

    it.each<[LoginMethod, number, Record<string, unknown>, string]>([
        ['saml', 200, { sso_enforcement: null }, '/login/saml/?email=user%40example.com&idp=posthog_custom'],
        ['google-oauth2', 200, { sso_enforcement: 'saml' }, '/login/saml/?email=user%40example.com&idp=posthog_custom'],
        ['google-oauth2', 500, {}, '/login/google-oauth2/?email=user%40example.com'],
    ])('sends a %s row with a %s precheck of %j to %s', async (method, status, response, redirectUrl) => {
        precheckStatus = status
        precheckResponse = response
        const login = selectRow(method)

        await expectLogic(recentLoginsLogic).toFinishAllListeners()
        expect(assignMock).toHaveBeenCalledWith(redirectUrl)
        expect(login.values.login.email).toEqual('')
        expect(recentLoginsLogic.values.checkingEmail).toBeNull()
    })

    it.each<LoginMethod>(['password', null])('opens the form with the email for a %s row', async (method) => {
        const login = selectRow(method)

        await expectLogic(login).toDispatchActions([login.actionCreators.precheck({ email: 'user@example.com' })])
        expect(assignMock).not.toHaveBeenCalled()
        expect(login.values.login.email).toEqual('user@example.com')
        expect(recentLoginsLogic.values.isChooserShown).toBe(false)
        expect(recentLoginsLogic.values.isPasswordFocusRequested).toBe(true)
    })

    it.each<[string, boolean, string, boolean, (login: ReturnType<typeof loginLogic.build>) => Promise<void> | void]>([
        ['with recent logins', true, '/login', true, () => {}],
        ['without recent logins', false, '/login', false, () => {}],
        ['after "Use another account"', false, '/login', true, () => recentLoginsLogic.actions.selectAnotherAccount()],
        [
            'after "Back to recent logins"',
            true,
            '/login',
            true,
            () => {
                recentLoginsLogic.actions.selectAnotherAccount()
                recentLoginsLogic.actions.returnToRecentLogins()
            },
        ],
        ['for an ?email= link', false, '/login?email=user%40example.com', true, () => {}],
        ['for an ?error_code= link', false, '/login?error_code=google_sso_enforced', true, () => {}],
        ['for an invite link', false, '/login?next=%2Fsignup%2Fabc', true, () => {}],
        [
            'for an account without a password',
            false,
            '/login',
            true,
            async (login) => {
                precheckResponse = { saml_available: false, password_login_available: false }
                login.actions.precheck({ email: 'user@example.com' })
                await expectLogic(login).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
            },
        ],
    ])('the recent logins list %s is shown: %s', async (_, chooserShown, url, hasRows, act) => {
        const login = mountLogin(url, hasRows)
        await act(login)

        expect(recentLoginsLogic.values.isChooserShown).toBe(chooserShown)
    })
})
