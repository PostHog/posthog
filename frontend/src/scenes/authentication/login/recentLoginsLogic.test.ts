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

    beforeEach(() => {
        Object.defineProperty(window.navigator, 'vendor', { value: WEBKIT_VENDOR, configurable: true }) // skip passkey auto-trigger
        precheckResponse = { saml_available: false }
        useMocks({ post: { '/api/login/precheck': () => [200, precheckResponse] } })
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

    function selectRow(method: LoginMethod): ReturnType<typeof loginLogic.build> {
        const login = loginLogic()
        login.mount()
        recentLoginsLogic.mount()
        recentLoginsLogic.actions.selectRecentLogin({
            email: 'user@example.com',
            method,
            lastUsedAt: '2026-10-01T10:00:00Z',
        })
        return login
    }

    it.each<[LoginMethod, string]>([
        ['saml', '/login/saml/?email=user%40example.com&idp=posthog_custom'],
        ['google-oauth2', '/login/google-oauth2/?email=user%40example.com'],
    ])('sends a %s row to %s', (method, redirectUrl) => {
        const login = selectRow(method)

        expect(assignMock).toHaveBeenCalledWith(redirectUrl)
        expect(login.values.login.email).toEqual('')
    })

    it.each<LoginMethod>(['password', null])('fills the form for a %s row without leaving the page', async (method) => {
        const login = selectRow(method)

        await expectLogic(login).toDispatchActions([login.actionCreators.precheck({ email: 'user@example.com' })])
        expect(assignMock).not.toHaveBeenCalled()
        expect(login.values.login.email).toEqual('user@example.com')
    })

    it.each([
        ['with recent logins', true, { hasRows: true, linkClicked: false, hasPassword: true }],
        ['after the link click', false, { hasRows: true, linkClicked: true, hasPassword: true }],
        ['for an account without a password', false, { hasRows: true, linkClicked: false, hasPassword: false }],
        ['without recent logins', false, { hasRows: false, linkClicked: false, hasPassword: true }],
    ])('other login methods %s are collapsed: %s', async (_, collapsed, { hasRows, linkClicked, hasPassword }) => {
        if (hasRows) {
            record('user@example.com', 'password')
        }
        precheckResponse = { saml_available: false, password_login_available: hasPassword }
        const login = loginLogic()
        login.mount()
        recentLoginsLogic.mount()
        login.actions.precheck({ email: 'user@example.com' })
        await expectLogic(login).toDispatchActions(['precheckSuccess']).toFinishAllListeners()
        if (linkClicked) {
            recentLoginsLogic.actions.showOtherLoginMethods()
        }

        expect(recentLoginsLogic.values.isOtherLoginMethodsCollapsed).toBe(collapsed)
    })
})
