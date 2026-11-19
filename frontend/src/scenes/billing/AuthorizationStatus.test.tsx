import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { AuthorizationStatus } from './AuthorizationStatus'

describe('AuthorizationStatus', () => {
    beforeEach(() => {
        initKeaTests()
        window.history.replaceState({}, '', '/billing/authorization_status?payment_intent=pi_old')
    })

    afterEach(() => {
        cleanup()
        window.history.replaceState({}, '', '/')
    })

    it('shows a way back to billing for an old callback without an organization', async () => {
        render(
            <Provider>
                <AuthorizationStatus />
            </Provider>
        )
        expect(
            await screen.findByText('This payment link is missing its organization. Return to billing and start again.')
        ).toBeInTheDocument()
        expect(screen.getByText('Return to billing').closest('a')).toHaveAttribute('href', '/organization/billing')
    })
})
