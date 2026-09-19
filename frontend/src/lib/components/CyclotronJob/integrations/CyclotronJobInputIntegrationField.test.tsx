import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

import { CyclotronJobInputIntegrationField } from './CyclotronJobInputIntegrationField'

const SLACK_INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'slack',
    display_name: 'Test workspace',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

const INTEGRATION_SCHEMA: CyclotronJobInputSchemaType = {
    type: 'integration',
    key: 'oauth',
    label: 'Google Ads account',
    integration: 'google-ads',
}

const FIELD_SCHEMA: CyclotronJobInputSchemaType = {
    type: 'integration_field',
    key: 'customerId',
    label: 'Customer ID',
    integration_key: 'oauth',
    integration_field: 'google_ads_customer_id',
}

describe('CyclotronJobInputIntegrationField', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': () => [200, { results: [SLACK_INTEGRATION] }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('asks for the right kind instead of loading a picker for a mismatched integration', async () => {
        // The stored id can point at an integration of another kind. The pickers call kind-specific
        // endpoints, so rendering one here would fail the request with nothing the user can act on.
        render(
            <Provider>
                <CyclotronJobInputIntegrationField
                    schema={FIELD_SCHEMA}
                    configuration={{
                        inputs: { oauth: { value: SLACK_INTEGRATION.id } },
                        inputs_schema: [INTEGRATION_SCHEMA, FIELD_SCHEMA],
                    }}
                />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText(/Select a Google Ads integration in Google Ads account/)).toBeInTheDocument()
        })
    })
})
