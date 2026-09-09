import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LoginForm } from './LoginForm'

const CLOUD_PREFLIGHT = {
    ...preflightJson,
    cloud: true,
    region: 'US',
    realm: 'cloud',
    available_social_auth_providers: { ...preflightJson.available_social_auth_providers, 'google-oauth2': true },
}
const PROVIDER_HINT = /This account can also sign in with Google\. Use the Google button below\./
const REGION_HINT = /It may live in our EU region/

async function submitAWrongPassword(): Promise<void> {
    window.POSTHOG_APP_CONTEXT = { current_user: null } as any
    initKeaTests()
    router.actions.push('/login')
    render(
        <Provider>
            <LoginForm />
        </Provider>
    )
    // Typing the password blurs the email field, which is what runs the precheck
    await userEvent.type(screen.getByTestId('login-email'), 'ann@example.com')
    await userEvent.type(screen.getByTestId('password'), 'wrong-password')
    await userEvent.click(screen.getByTestId('password-login'))
}

describe('LoginForm', () => {
    describe.each([
        [
            'names the linked provider on the account',
            [200, { saml_available: false, password_login_available: true, social_providers: ['google-oauth2'] }],
            PROVIDER_HINT,
            REGION_HINT,
        ],
        [
            'guesses the other region when the account has no linked provider',
            [200, { saml_available: false, password_login_available: true, social_providers: [] }],
            REGION_HINT,
            PROVIDER_HINT,
        ],
        [
            'guesses the other region when the precheck failed, because its defaults are not the account',
            [429, {}],
            REGION_HINT,
            PROVIDER_HINT,
        ],
    ])('after a failed password login, %s', (_label, precheck, shown, hidden) => {
        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
                    '/_preflight': () => [200, CLOUD_PREFLIGHT],
                },
                post: {
                    '/api/login/precheck': () => precheck,
                    '/api/login': () => [401, { code: 'invalid_credentials', detail: 'Invalid email or password.' }],
                },
            })
            await submitAWrongPassword()
        })

        afterEach(() => {
            cleanup()
        })

        it('shows one hint', async () => {
            expect(await screen.findByText(shown)).toBeInTheDocument()
            expect(screen.queryByText(hidden)).not.toBeInTheDocument()
        })
    })

    describe('after a failed password login with a failed preflight request', () => {
        beforeEach(async () => {
            // The preflight request fails on purpose, so keep its expected error out of the output
            silenceKeaLoadersErrors()
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
                    '/_preflight': () => [500, {}],
                },
                post: {
                    '/api/login/precheck': () => [
                        200,
                        { saml_available: false, password_login_available: true, social_providers: ['google-oauth2'] },
                    ],
                    '/api/login': () => [401, { code: 'invalid_credentials', detail: 'Invalid email or password.' }],
                },
            })
            await submitAWrongPassword()
        })

        afterEach(() => {
            resumeKeaLoadersErrors()
            cleanup()
        })

        it('shows no hint, because the page has no provider button to point at', async () => {
            expect(await screen.findByText(/Invalid email or password/)).toBeInTheDocument()
            expect(screen.queryByText(PROVIDER_HINT)).not.toBeInTheDocument()
            expect(screen.queryByText(REGION_HINT)).not.toBeInTheDocument()
        })
    })
})
