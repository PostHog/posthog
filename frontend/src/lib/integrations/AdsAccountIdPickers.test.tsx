import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { GoogleAdsConversionActionPicker, GoogleAdsCustomerIdPicker } from './GoogleAdsIntegrationHelpers'
import { LinkedInAdsAccountIdPicker } from './LinkedInIntegrationHelpers'

const INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'linkedin-ads',
    display_name: 'Ads account',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

describe('ads account ID pickers', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // A disabled picker never loads its account list, so the fallback option built from the saved value renders.
    test.each([
        { name: 'LinkedIn Ads', Picker: LinkedInAdsAccountIdPicker, value: 123456789, label: '123456789' },
        { name: 'Google Ads', Picker: GoogleAdsCustomerIdPicker, value: 1234567890, label: '123-456-7890' },
    ])('$name picker renders a numeric saved ID', ({ Picker, value, label }) => {
        render(
            <Provider>
                <Picker integration={INTEGRATION} value={value as unknown as string} disabled />
            </Provider>
        )

        expect(screen.getByText(label)).toBeInTheDocument()
    })

    test('Google Ads conversion action picker loads actions for a numeric saved customer ID', async () => {
        const requestedCustomerIds: (string | null)[] = []
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/google_conversion_actions': ({ request }) => {
                    requestedCustomerIds.push(new URL(request.url).searchParams.get('customerId'))
                    return [200, { conversionActions: [] }]
                },
            },
        })

        render(
            <Provider>
                <GoogleAdsConversionActionPicker
                    integration={INTEGRATION}
                    requiresFieldValue={1234567890 as unknown as string}
                />
            </Provider>
        )

        await waitFor(() => expect(requestedCustomerIds).toEqual(['1234567890']))
    })
})
