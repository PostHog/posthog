import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ConfirmOrganization } from './ConfirmOrganization'

describe('ConfirmOrganization', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // The page only renders for a logged-out person
                '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
            },
        })
        window.POSTHOG_APP_CONTEXT = { current_user: null } as any
        initKeaTests()
        // The social signup redirect fills in everything except the organization name
        router.actions.push('/organization/confirm-creation', { email: 'spike@spike.com', first_name: 'Spike' })
        render(
            <Provider>
                <ConfirmOrganization />
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
    })

    it('points a failed submit at the organization name input', async () => {
        await userEvent.click(screen.getByText('Create organization'))

        expect(screen.getByLabelText('Organization name')).toHaveFocus()
        expect(screen.getByText(/You can use your own name/)).toBeInTheDocument()
    })

    it('prompts for a role while the dropdown has nothing selected', () => {
        // The form defaults the role to an empty string, which LemonSelect would otherwise render
        // as a blank button
        expect(screen.getByText('Select your role')).toBeInTheDocument()
    })
})
