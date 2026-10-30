import {
    PENDING_OAUTH_CONNECTION_FIXTURE,
    setPendingOAuthConnectionCookie,
} from 'scenes/authentication/shared/pendingOAuthConnection.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { PreflightStatus } from '~/types'

import { AuthAccountPath, accountPathFor, authLogic, canSignUpWithEmail } from './authLogic'
import { authTelemetryLogic } from './authTelemetryLogic'
import { PrecheckResponseType } from './loginLogic'
import { loginLogic } from './loginLogic'
import { maintenanceSignupRedirectUrl, signupLogic } from './signupLogic'

jest.mock('posthog-js')

const COMPLETED: PrecheckResponseType = { status: 'completed', saml_available: false }
const PREFLIGHT = { can_create_org: true, demo: false } as PreflightStatus

describe('authLogic', () => {
    it.each<[string, PrecheckResponseType, PreflightStatus, AuthAccountPath]>([
        ['an existing account', { ...COMPLETED, account_exists: true }, PREFLIGHT, 'login'],
        ['a new email', { ...COMPLETED, account_exists: false }, PREFLIGHT, 'signup'],
        [
            'a failed precheck',
            { ...COMPLETED, precheckFailed: true, password_login_available: true },
            PREFLIGHT,
            'login',
        ],
        [
            'a new email on an SSO-enforced domain',
            { ...COMPLETED, account_exists: false, sso_enforcement: 'saml' },
            PREFLIGHT,
            'login',
        ],
        [
            'a new email on a domain with optional SAML',
            { ...COMPLETED, account_exists: false, saml_available: true },
            PREFLIGHT,
            'login',
        ],
        [
            'a new email where no organization can be created',
            { ...COMPLETED, account_exists: false },
            { ...PREFLIGHT, can_create_org: false },
            'login',
        ],
        ['an existing demo user', { ...COMPLETED, account_exists: true }, { ...PREFLIGHT, demo: true }, 'signup'],
    ])('routes %s to the right step', (_name, precheck, preflight, expected) => {
        expect(accountPathFor(precheck, preflight)).toEqual(expected)
    })

    it.each<[string, PrecheckResponseType, PreflightStatus, boolean]>([
        ['an instance that creates organizations', COMPLETED, PREFLIGHT, true],
        ['an instance that cannot create organizations', COMPLETED, { ...PREFLIGHT, can_create_org: false }, false],
        ['an SSO-enforced domain', { ...COMPLETED, sso_enforcement: 'saml' }, PREFLIGHT, false],
    ])('offers email signup to a new person on %s: %s', (_name, precheck, preflight, expected) => {
        expect(canSignUpWithEmail(precheck, preflight)).toEqual(expected)
    })

    const US = { cloud: true, region: 'US' as PreflightStatus['region'] }
    it.each<[string, Partial<PreflightStatus>, string | undefined, boolean, string | null]>([
        [
            'sends a US signup to the EU with its email',
            US,
            'eu',
            false,
            'https://eu.posthog.com/signup?maintenanceRedirect=true&email=person%40example.com',
        ],
        [
            'keeps a signup in the region that takes them',
            { ...US, region: 'EU' as PreflightStatus['region'] },
            'eu',
            false,
            null,
        ],
        ['keeps a signup when the flag is off', US, undefined, false, null],
        ['keeps a self-hosted signup', { ...US, cloud: false }, 'eu', false, null],
        ['keeps a signup with a pending OAuth connection', US, 'eu', true, null],
    ])('maintenance redirect %s', (_name, preflight, flag, pendingOAuthConnection, expected) => {
        setPendingOAuthConnectionCookie(pendingOAuthConnection ? PENDING_OAUTH_CONNECTION_FIXTURE : null)
        const featureFlags = flag ? { 'redirect-signups-to-instance': flag } : {}
        expect(
            maintenanceSignupRedirectUrl({ ...PREFLIGHT, ...preflight }, featureFlags, 'person@example.com')
        ).toEqual(expected)
    })

    describe('when a request fails', () => {
        let loginPrecheck: () => [number, Record<string, any>]
        let signupPrecheck: () => [number, Record<string, any>]

        beforeEach(() => {
            loginPrecheck = () => [200, { account_exists: false, saml_available: false }]
            signupPrecheck = () => [200, { email_exists: false, pending_invite: null }]
            useMocks({
                get: {
                    '/_preflight': () => [200, { ...preflightJson, can_create_org: true }],
                },
                post: {
                    '/api/login/precheck': () => loginPrecheck(),
                    '/api/signup/precheck': () => signupPrecheck(),
                },
            })
            initKeaTests()
            router.actions.push('/login')
            authLogic.mount()
            loginLogic.actions.setLoginValue('email', 'person@example.com')
        })

        afterEach(() => {
            authLogic.unmount()
        })

        it('lands on the login step with the account unknown, and still lets the person sign up', async () => {
            loginPrecheck = () => [429, { type: 'throttled_error', code: 'throttled', detail: 'Slow down' }]

            await expectLogic(authLogic, () => authLogic.actions.continueWithEmail())
                .toDispatchActions(['chooseAccountPath'])
                .toMatchValues({ step: 'login', accountExists: null })

            authLogic.actions.chooseAccountPath('signup', null)
            await expectLogic(signupLogic).toDispatchActions(['finishSignupEmailPrecheck'])
            await expectLogic(authLogic).toMatchValues({ step: 'signup_credentials' })
        })

        it('offers login for an email that signup finds taken, with the password field', async () => {
            signupPrecheck = () => [
                409,
                {
                    email_exists: true,
                    code: 'account_exists',
                    detail: 'There is already an account with this email address.',
                },
            ]

            await expectLogic(authLogic, () => authLogic.actions.continueWithEmail()).toDispatchActions([
                'chooseAccountPath',
            ])
            await expectLogic(signupLogic).toDispatchActions(['setSignupEmailError']).toMatchValues({
                signupEmailTaken: true,
            })
            await expectLogic(authLogic).toMatchValues({ step: 'email' })

            authLogic.actions.chooseAccountPath('login', true)
            await expectLogic(authLogic).toMatchValues({ step: 'login', accountExists: true, emailError: null })
        })

        it('drops the passkey registered for the previous email when the person changes it', async () => {
            await expectLogic(authLogic, () => authLogic.actions.continueWithEmail()).toDispatchActions([
                'chooseAccountPath',
            ])
            await expectLogic(signupLogic).toDispatchActions(['finishSignupEmailPrecheck'])
            signupLogic.actions.setPasskeyRegistered(true)

            authLogic.actions.backToEmail()
            await expectLogic(signupLogic).toMatchValues({ passkeyRegistered: false })
        })

        it('opens the next password field without the error a failed login submit left behind', async () => {
            loginLogic.actions.submitLogin()
            await expectLogic(loginLogic).toDispatchActions(['submitLoginFailure'])

            expect(loginLogic.values.loginErrors.password).toBeTruthy()

            authLogic.actions.backToEmail()
            await expectLogic(loginLogic).toMatchValues({ loginErrors: {} })
        })
    })

    describe('funnel events', () => {
        let accountExists: boolean
        let holdPrecheck: Promise<void> | null

        beforeEach(() => {
            accountExists = false
            holdPrecheck = null
            useMocks({
                get: {
                    '/_preflight': () => [200, { ...preflightJson, can_create_org: true }],
                },
                post: {
                    '/api/login/precheck': async () => {
                        await holdPrecheck
                        return [200, { account_exists: accountExists, saml_available: false }]
                    },
                    '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                },
            })
            initKeaTests()
            jest.mocked(posthog.capture).mockClear()
            router.actions.push('/signup')
            authLogic.mount()
            authTelemetryLogic.mount()
        })

        afterEach(() => {
            authTelemetryLogic.unmount()
            authLogic.unmount()
        })

        function capturedEvents(): [string, Record<string, any>][] {
            return jest
                .mocked(posthog.capture)
                .mock.calls.filter(([name]) => name.startsWith('auth '))
                .map(([name, properties]) => [name, properties as Record<string, any>])
        }

        it.each<[string, boolean, AuthAccountPath, string]>([
            ['a new email', false, 'signup', 'signup_credentials'],
            ['an existing account', true, 'login', 'login'],
        ])('reports each step of %s once, plus the routing decision', async (_name, exists, path, step) => {
            accountExists = exists
            loginLogic.actions.setLoginValue('email', 'person@example.com')

            await expectLogic(authLogic, () => authLogic.actions.continueWithEmail()).toDispatchActions([
                'chooseAccountPath',
            ])
            if (path === 'signup') {
                await expectLogic(signupLogic).toDispatchActions(['finishSignupEmailPrecheck'])
            }

            const [first, ...rest] = capturedEvents()
            expect(first).toEqual(['auth step viewed', expect.objectContaining({ step: 'email', entry: 'signup' })])
            expect(rest).toHaveLength(2)
            expect(rest).toEqual(
                expect.arrayContaining([
                    [
                        'auth email submitted',
                        expect.objectContaining({ entry: 'signup', routed_to: path, account_exists: exists }),
                    ],
                    ['auth step viewed', expect.objectContaining({ step, entry: 'signup' })],
                ])
            )
        })

        it('ignores a precheck answer for an email the person has since changed', async () => {
            accountExists = true
            let releasePrecheck = (): void => {}
            holdPrecheck = new Promise((resolve) => {
                releasePrecheck = resolve
            })
            loginLogic.actions.setLoginValue('email', 'first@example.com')
            authLogic.actions.continueWithEmail()
            loginLogic.actions.setLoginValue('email', 'second@example.com')
            releasePrecheck()

            await expectLogic(loginLogic).toDispatchActions(['precheckSuccess'])
            await expectLogic(authLogic).toNotHaveDispatchedActions(['chooseAccountPath']).toMatchValues({
                step: 'email',
                isEmailSubmitting: false,
            })
        })
    })
})
