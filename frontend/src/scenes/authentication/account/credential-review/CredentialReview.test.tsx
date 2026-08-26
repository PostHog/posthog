import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CredentialReview } from './CredentialReview'

describe('<CredentialReview />', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/personal_api_keys': () => [200, []],
                '/api/webauthn/credentials/': () => [200, []],
                '/api/oauth/connected-apps/': () => [200, []],
            },
        })
    })

    it('shows the Continue button as loading while the review POST is in flight', async () => {
        // A never-resolving POST keeps the button in its pending state so we can assert it.
        jest.spyOn(api, 'create').mockImplementation(async () => await new Promise(() => undefined))

        render(<CredentialReview />)

        const getButton = (): HTMLButtonElement =>
            screen.getByText('Continue to PostHog').closest('button') as HTMLButtonElement

        // The button starts disabled while the credential lists load, then enables.
        await waitFor(() => expect(getButton()).toHaveAttribute('aria-disabled', 'false'), { timeout: 3000 })

        await userEvent.click(getButton())

        // LemonButton's loading state marks the trigger aria-disabled, so a second click cannot fire.
        expect(getButton()).toHaveAttribute('aria-disabled', 'true')
    })
})
