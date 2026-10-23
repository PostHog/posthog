import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { PrecheckResponseType } from 'scenes/authentication/login/loginLogic'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { signupLogic } from 'scenes/authentication/signup/signupForm/signupLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AuthAccountPath, accountPathFor, authLogic } from './authLogic'
import { authTelemetryLogic } from './authTelemetryLogic'

jest.mock('posthog-js')

const COMPLETED: PrecheckResponseType = { status: 'completed', saml_available: false }

describe('authLogic', () => {
    it.each<[string, PrecheckResponseType, { isDemo: boolean; canCreateOrg: boolean }, AuthAccountPath]>([
        ['an existing account', { ...COMPLETED, account_exists: true }, { isDemo: false, canCreateOrg: true }, 'login'],
        ['a new email', { ...COMPLETED, account_exists: false }, { isDemo: false, canCreateOrg: true }, 'signup'],
        [
            'a failed precheck',
            { ...COMPLETED, precheckFailed: true, password_login_available: true },
            { isDemo: false, canCreateOrg: true },
            'login',
        ],
        [
            'a new email on an SSO-enforced domain',
            { ...COMPLETED, account_exists: false, sso_enforcement: 'saml' },
            { isDemo: false, canCreateOrg: true },
            'login',
        ],
        [
            'a new email where no organization can be created',
            { ...COMPLETED, account_exists: false },
            { isDemo: false, canCreateOrg: false },
            'login',
        ],
        [
            'an existing demo user',
            { ...COMPLETED, account_exists: true },
            { isDemo: true, canCreateOrg: true },
            'signup',
        ],
    ])('routes %s to the right step', (_name, precheck, instance, expected) => {
        expect(accountPathFor(precheck, instance)).toEqual(expected)
    })

    describe('funnel events', () => {
        let accountExists: boolean

        beforeEach(() => {
            accountExists = false
            useMocks({
                get: {
                    '/_preflight': () => [200, { ...preflightJson, can_create_org: true }],
                },
                post: {
                    '/api/login/precheck': () => [200, { account_exists: accountExists, saml_available: false }],
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
        ])(
            'reports each step of %s once, with the routing decision between them',
            async (_name, exists, path, step) => {
                accountExists = exists
                loginLogic.actions.setLoginValue('email', 'person@example.com')

                await expectLogic(authLogic, () => authLogic.actions.continueWithEmail()).toDispatchActions([
                    'chooseAccountPath',
                ])
                if (path === 'signup') {
                    await expectLogic(signupLogic).toDispatchActions(['submitSignupPanelEmailSuccess'])
                }

                expect(capturedEvents()).toEqual([
                    ['auth step viewed', expect.objectContaining({ step: 'email', entry: 'signup' })],
                    [
                        'auth email submitted',
                        expect.objectContaining({ entry: 'signup', routed_to: path, account_exists: exists }),
                    ],
                    ['auth step viewed', expect.objectContaining({ step, entry: 'signup' })],
                ])
            }
        )
    })
})
