import { fireEvent, render } from '@testing-library/react'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { ItemCategory } from '..'
import { LazyEventDetailsRenderer } from './eventDetails'

const STORED_EVENT: Record<string, unknown> = {
    uuid: 'event-uuid-1',
    event: '$pageview',
    timestamp: '2026-01-01T00:00:00.000Z',
    properties: JSON.stringify({ $current_url: 'https://example.com' }),
    distinct_id: 'user-distinct-id-1',
}

describe('LazyEventDetailsRenderer', () => {
    beforeEach(() => {
        initKeaTests()
        // Answer with the columns the request selects, so a column the query omits comes back missing.
        jest.spyOn(api, 'query').mockImplementation(async (query: any) => ({
            results: [query.select.map((column: string) => STORED_EVENT[column])],
        }))
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('shows the event distinct id in the metadata tab', async () => {
        const { findByText } = render(
            <LazyEventDetailsRenderer
                item={{
                    id: 'event-uuid-1',
                    category: ItemCategory.PAGE_VIEWS,
                    timestamp: dayjs('2026-01-01T00:00:00.000Z'),
                    payload: {},
                }}
            />
        )

        fireEvent.click(await findByText('Metadata'))

        expect(await findByText('user-distinct-id-1')).toBeTruthy()
    })
})
