import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { ItemCategory } from '..'
import { CombinedEventLoader } from './combined'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: { query: jest.fn() },
}))

const mockedQuery = api.query as jest.Mock

describe('CombinedEventLoader', () => {
    beforeEach(() => {
        mockedQuery.mockReset()
    })

    it('fetches $screen events and groups them under views with the screen name', async () => {
        // uuid, event, timestamp, $lib, $current_url, $exception_list, $exception_fingerprint, $exception_issue_id, $screen_name
        mockedQuery.mockResolvedValue({
            results: [
                ['uuid-1', '$screen', '2024-07-09T12:00:00.000Z', 'posthog-ios', null, null, null, null, 'Checkout'],
            ],
        })

        const loader = new CombinedEventLoader('session-1', dayjs.utc('2024-07-09T12:00:00.000Z'))
        const { items } = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:01.000Z'), 10)

        const where = (mockedQuery.mock.calls[0][0].where as string[]).join(' ')
        expect(where).toContain("equals(event, '$screen')")

        expect(items).toHaveLength(1)
        expect(items[0].category).toBe(ItemCategory.PAGE_VIEWS)
        expect(items[0].payload.screenName).toBe('Checkout')
    })
})
