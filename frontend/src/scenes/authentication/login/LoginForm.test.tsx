import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LoginForm } from './LoginForm'
import { loginLogic } from './loginLogic'

describe('<LoginForm />', () => {
    let login: ReturnType<typeof loginLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/_preflight': () => [200, { cloud: true, region: 'US', available_social_auth_providers: {} }],
            },
            post: {
                '/api/login/precheck': () => [200, { saml_available: false }],
            },
        })
        initKeaTests()
        preflightLogic.mount()
        login = loginLogic()
        login.mount()
        login.actions.setLoginValue('email', 'test@posthog.com')
    })

    afterEach(() => {
        cleanup()
    })

    it('offers a password reset when the credentials are rejected', async () => {
        login.actions.setGeneralError('invalid_credentials', 'Invalid email or password.')
        render(<LoginForm />)

        await userEvent.click(screen.getByTestId('login-error-reset-password'))

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual('/reset')
        expect(router.values.searchParams.email).toEqual('test@posthog.com')
    })

    it('does not offer a password reset for an error a reset cannot fix', () => {
        login.actions.setGeneralError('sso_enforced', "Please log in with your organization's required SSO method.")
        render(<LoginForm />)

        expect(screen.queryByTestId('login-error-reset-password')).not.toBeInTheDocument()
    })
})
