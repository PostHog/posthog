import { performQuery } from '~/queries/query'

import { loadQueryData } from './liveWebAnalyticsMetricsLogic'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const ALWAYS_PRESENT_RESPONSE_KEYS = [
    'usersPageviewsResponse',
    'deviceResponse',
    'browserResponse',
    'pathsResponse',
    'referrerResponse',
    'geoResponse',
    'botResponse',
] as const

const runLoad = (): ReturnType<typeof loadQueryData> =>
    // No filters and no city breakdown, so recentUsers + city queries are skipped:
    // the 7 always-present queries are the ones exercised here.
    loadQueryData({
        dateFrom: new Date('2024-01-01T00:00:00Z'),
        dateTo: new Date('2024-01-01T00:30:00Z'),
        filters: [],
        includeCity: false,
        filtersEnabled: true,
    })

describe('loadQueryData', () => {
    const mockPerformQuery = performQuery as jest.Mock

    beforeEach(() => {
        mockPerformQuery.mockReset()
    })

    it('reports no failures and returns every response when all queries succeed', async () => {
        mockPerformQuery.mockResolvedValue({ results: [] })

        const { responses, attempted, failed } = await runLoad()

        expect(attempted).toBe(7)
        expect(failed).toBe(0)
        for (const key of ALWAYS_PRESENT_RESPONSE_KEYS) {
            expect(responses[key]).not.toBeNull()
        }
        // Skipped optional queries come back as null rather than as failures.
        expect(responses.recentUsersResponse).toBeNull()
        expect(responses.cityResponse).toBeNull()
    })

    it('still resolves with partial results when a single query rejects', async () => {
        let call = 0
        mockPerformQuery.mockImplementation(() => {
            call += 1
            // Reject exactly one of the concurrent queries; the rest succeed.
            return call === 2 ? Promise.reject(new Error('boom')) : Promise.resolve({ results: [] })
        })

        const { responses, attempted, failed } = await runLoad()

        expect(attempted).toBe(7)
        expect(failed).toBe(1)
        const nullCount = ALWAYS_PRESENT_RESPONSE_KEYS.filter((key) => responses[key] === null).length
        expect(nullCount).toBe(1)
    })

    it('marks a total failure when every query rejects', async () => {
        mockPerformQuery.mockRejectedValue(new Error('backend down'))

        const { responses, attempted, failed } = await runLoad()

        expect(attempted).toBe(7)
        expect(failed).toBe(7)
        for (const key of ALWAYS_PRESENT_RESPONSE_KEYS) {
            expect(responses[key]).toBeNull()
        }
    })
})
