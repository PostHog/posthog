import api from 'lib/api'

import { fetchCrossProjectTile } from './crossProjectTileFetch'

jest.mock('lib/api', () => ({ __esModule: true, default: { get: jest.fn() } }))

const mockedGet = api.get as jest.Mock

describe('fetchCrossProjectTile', () => {
    beforeEach(() => {
        mockedGet.mockReset()
    })

    it('fetches from the tile own project, not the current one', async () => {
        mockedGet.mockResolvedValue({ id: 7, name: 'Signups' })

        await fetchCrossProjectTile(42, 7)

        expect(mockedGet).toHaveBeenCalledTimes(1)
        expect(mockedGet.mock.calls[0][0]).toContain('api/projects/42/insights/7/')
    })

    it('returns the insight when the project endpoint answers', async () => {
        mockedGet.mockResolvedValue({ id: 7, name: 'Signups' })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBeNull()
        expect(result.insight).toEqual({ id: 7, name: 'Signups' })
    })

    it('reports no access on 403 and carries no insight', async () => {
        mockedGet.mockRejectedValue({ status: 403 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('no-access')
        expect(result.insight).toBeNull()
    })

    it('reports not found on 404', async () => {
        mockedGet.mockRejectedValue({ status: 404 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('not-found')
        expect(result.insight).toBeNull()
    })

    it('reports a generic failure on any other error', async () => {
        mockedGet.mockRejectedValue({ status: 500 })

        const result = await fetchCrossProjectTile(42, 7)

        expect(result.unavailable).toBe('failed')
    })

    it('passes dashboard filters through as filters_override', async () => {
        mockedGet.mockResolvedValue({ id: 7 })

        await fetchCrossProjectTile(42, 7, { date_from: '-7d' })

        expect(mockedGet.mock.calls[0][0]).toContain('filters_override=')
        expect(decodeURIComponent(mockedGet.mock.calls[0][0])).toContain('"date_from":"-7d"')
    })

    it('omits filters_override when there are no filters', async () => {
        mockedGet.mockResolvedValue({ id: 7 })

        await fetchCrossProjectTile(42, 7, {})

        expect(mockedGet.mock.calls[0][0]).not.toContain('filters_override')
    })
})
