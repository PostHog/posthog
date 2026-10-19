import { insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { fetchCrossProjectTile } from './crossProjectTileFetch'

jest.mock('products/product_analytics/frontend/generated/api', () => ({
    __esModule: true,
    insightsRetrieve: jest.fn(),
}))

const mockedRetrieve = insightsRetrieve as jest.Mock

describe('fetchCrossProjectTile', () => {
    beforeEach(() => {
        mockedRetrieve.mockReset()
    })

    it('fetches from the tile own project, not the current one', async () => {
        mockedRetrieve.mockResolvedValue({ id: 7, name: 'Signups' })

        await fetchCrossProjectTile(42, 7)

        expect(mockedRetrieve).toHaveBeenCalledTimes(1)
        expect(mockedRetrieve).toHaveBeenCalledWith('42', 7, expect.anything())
    })

    it('returns the insight when the project endpoint answers', async () => {
        mockedRetrieve.mockResolvedValue({ id: 7, name: 'Signups' })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBeNull()
        expect(result.insight).toEqual({ id: 7, name: 'Signups' })
    })

    it('reports no access on 403 and carries no insight', async () => {
        mockedRetrieve.mockRejectedValue({ status: 403 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('no-access')
        expect(result.insight).toBeNull()
    })

    it('reports not found on 404', async () => {
        mockedRetrieve.mockRejectedValue({ status: 404 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('not-found')
        expect(result.insight).toBeNull()
    })

    it('reports a generic failure on any other error', async () => {
        mockedRetrieve.mockRejectedValue({ status: 500 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('failed')
    })

    it('passes dashboard filters through as filters_override', async () => {
        mockedRetrieve.mockResolvedValue({ id: 7 })

        await fetchCrossProjectTile(42, 7, { date_from: '-7d' })

        expect(JSON.parse(mockedRetrieve.mock.calls[0][2].filters_override)).toEqual({ date_from: '-7d' })
    })

    it('omits filters_override when there are no filters', async () => {
        mockedRetrieve.mockResolvedValue({ id: 7 })

        await fetchCrossProjectTile(42, 7, {})

        expect(mockedRetrieve.mock.calls[0][2]).not.toHaveProperty('filters_override')
    })
})
