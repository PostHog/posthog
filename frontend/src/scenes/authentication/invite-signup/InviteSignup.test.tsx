import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InviteSignup } from './InviteSignup'
import { inviteSignupLogic } from './inviteSignupLogic'

describe('InviteSignup', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // The signup form only renders for a logged-out person
                '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
                '/api/signup/1234/': () => [
                    200,
                    { id: '1234', target_email: 'jane@example.com', first_name: 'Jane', organization_name: 'Example' },
                ],
            },
            post: {
                '/api/login/precheck': () => [200, { sso_enforcement: null, saml_available: false }],
            },
        })
        window.POSTHOG_APP_CONTEXT = { current_user: null } as any
        initKeaTests()
        inviteSignupLogic.mount()
        router.actions.push('/signup/1234')
        render(
            <Provider>
                <InviteSignup />
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
    })

    it('points a submit with no password at the password input', async () => {
        const passwordInput = await screen.findByPlaceholderText('••••••••••')
        await userEvent.click(await screen.findByText(/Join Example/))

        expect(passwordInput).toHaveFocus()
        expect(screen.getByText('Please enter your password to continue')).toBeInTheDocument()
    })

    it('marks the role as optional, because this form submits without one', async () => {
        expect((await screen.findByText('What is your role?')).closest('label')).toHaveTextContent('(optional)')
    })
})
