import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'

import { HogQLQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { LiveWebAnalyticsMetrics } from './LiveWebAnalyticsMetrics'

describe('LiveWebAnalyticsMetrics', () => {
    it('shows each card as its own backfill query lands', async () => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_ORGANIZATION)
        let openLocationsGate: () => void = () => {}
        const locationsGate = new Promise<void>((resolve) => {
            openLocationsGate = resolve
        })
        jest.spyOn(api, 'query')
        ;(api.query as jest.Mock).mockImplementation(async (query: HogQLQuery | TrendsQuery) => {
            if (query.tags?.name === 'live_geo') {
                await locationsGate
            }
            return { results: [] }
        })

        render(
            <Provider>
                <LiveWebAnalyticsMetrics />
            </Provider>
        )

        await waitFor(() => expect(screen.getByText('No device data')).toBeTruthy())
        expect(screen.queryByText('No country data')).toBeNull()

        openLocationsGate()
        await waitFor(() => expect(screen.getByText('No country data')).toBeTruthy())
    })
})
