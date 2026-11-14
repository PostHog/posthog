import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { GoogleAdsCustomerIdPicker } from './GoogleAdsIntegrationHelpers'
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

    // An agent or API client can store the account ID input as a number, because the backend does not
    // type-check integration_field inputs. The picker is disabled here so the account list stays null and
    // the fallback option built from the saved value is what renders.
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
})
