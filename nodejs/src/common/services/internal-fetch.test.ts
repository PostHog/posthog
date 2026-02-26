import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { internalFetch } from '~/utils/request'

import { InternalFetchService } from './internal-fetch'

jest.mock('~/utils/request', () => ({
    internalFetch: jest.fn(),
}))

describe('InternalFetchService', () => {
    it('calls internalFetch with internal auth header', async () => {
        const internalFetchService = new InternalFetchService({
            INTERNAL_API_SECRET: 'secret-123',
            INTERNAL_API_BASE_URL: 'https://internal.example.com',
        })
        const mockedInternalFetch = jest.mocked(internalFetch)

        mockedInternalFetch.mockImplementationOnce((_url, _fetchParams) => {
            return Promise.resolve({
                status: 200,
                headers: { 'Content-Type': 'application/json' },
                json: async () => Promise.resolve({ success: true }),
                text: async () => Promise.resolve(JSON.stringify({ success: true })),
                dump: async () => {},
            })
        })

        await internalFetchService.fetch({
            urlPath: '/health' as const,
            fetchParams: { method: 'POST', headers: { 'X-Test': 'abc' } } as any,
        })

        expect(mockedInternalFetch).toHaveBeenCalledTimes(1)
        expect(mockedInternalFetch.mock.calls[0][0]).toEqual('https://internal.example.com/health')
        expect(mockedInternalFetch.mock.calls[0][1]).toMatchObject({
            method: 'POST',
            headers: {
                'X-Test': 'abc',
                [INTERNAL_SERVICE_CALL_HEADER_NAME.toLowerCase()]: 'secret-123',
            },
        })
    })

    it('returns exceptions from internalFetch', async () => {
        const internalFetchService = new InternalFetchService({
            INTERNAL_API_SECRET: 'secret-123',
            INTERNAL_API_BASE_URL: 'https://internal.example.com',
        })
        const mockedInternalFetch = jest.mocked(internalFetch)

        mockedInternalFetch.mockRejectedValueOnce(new Error('boom'))

        await expect(
            internalFetchService.fetch({
                urlPath: '/boom' as const,
                fetchParams: { method: 'GET' } as any,
            })
        ).resolves.toEqual({ fetchError: new Error('boom'), fetchResponse: null })
    })
})
