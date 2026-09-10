import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InviteSignupForm } from './InviteSignupForm'

describe('InviteSignupForm', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
            },
        })
        // initKeaTests bootstraps a logged-in user unless current_user is pre-set; these cases
        // are about the visitor who has no session
        window.POSTHOG_APP_CONTEXT = { current_user: null } as any
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['invalid_invite', 'Log in'],
        ['expired', 'Log in'],
        ['unknown', 'Try again'],
    ])('offers the action that can recover a %s link', (errorCode, action) => {
        router.actions.push('/signup/abc-123', { error_code: errorCode })

        render(
            <Provider>
                <InviteSignupForm />
            </Provider>
        )

        expect(screen.getByText(action)).toBeInTheDocument()
    })
})
