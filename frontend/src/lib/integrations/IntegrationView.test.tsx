import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { IntegrationView } from './IntegrationView'

const INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'meta-ads',
    display_name: 'Ad account',
    config: {},
    created_at: '2026-01-02T00:00:00Z',
    created_by: null,
    errors: '',
    icon_url: '/static/services/meta-ads.png',
}

describe('IntegrationView', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/integrations': () => [200, { results: [] }] } })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // A connection the vendor no longer accepts read as connected, which is what left people
    // hunting for a way to reconnect a source that had already stopped syncing.
    it('does not call a connection with an authentication error connected', () => {
        render(
            <Provider>
                <IntegrationView integration={{ ...INTEGRATION, errors: 'TOKEN_REFRESH_FAILED' }} />
            </Provider>
        )

        expect(screen.getByText(/^Connection expired to/)).toBeInTheDocument()
        expect(screen.queryByText(/^Connected to/)).not.toBeInTheDocument()
    })

    it('calls a working connection connected', () => {
        render(
            <Provider>
                <IntegrationView integration={INTEGRATION} />
            </Provider>
        )

        expect(screen.getByText(/^Connected to/)).toBeInTheDocument()
        expect(screen.queryByText(/^Connection expired/)).not.toBeInTheDocument()
    })
})
