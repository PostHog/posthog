import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { GoogleAdsCustomerIdPicker, normalizeCustomerIdValue } from './GoogleAdsIntegrationHelpers'

const INTEGRATION = { id: 1, kind: 'google-ads' } as IntegrationType

const renderPicker = (): void => {
    render(
        <Provider>
            <GoogleAdsCustomerIdPicker integration={INTEGRATION} />
        </Provider>
    )
}

describe('GoogleAdsCustomerIdPicker', () => {
    // The destination reads the stored value as `<customer id>/<login customer id>`, so a typed value
    // without the second half sends an empty login-customer-id header and every upload fails.
    test.each([
        ['a picked option', '1234567890/6501924158', '1234567890/6501924158'],
        ['a typed customer id', '1234567890', '1234567890/1234567890'],
        ['a typed customer id with dashes', '123-456-7890', '1234567890/1234567890'],
        ['a typed pair with dashes', '123-456-7890/650-192-4158', '1234567890/6501924158'],
        ['a value with no digits', 'my account', null],
    ])('normalizes %s', (_name, value, expected) => {
        expect(normalizeCustomerIdValue(value)).toEqual(expected)
    })

    it('shows why the account list is short, and how to continue', async () => {
        // The walk used to fail silently, so the picker showed a short list with no message.
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/google_accessible_accounts': () => [
                    400,
                    { detail: 'Google Ads did not return all of the accounts you can use. Please try again.' },
                ],
            },
        })
        initKeaTests()

        renderPicker()

        expect(await screen.findByText(/did not return all of the accounts/)).toBeInTheDocument()
        expect(screen.getByText(/type the 10-digit customer ID/)).toBeInTheDocument()
    })
})
