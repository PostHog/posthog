import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { cdpTrackedFetch } from '~/cdp/services/hog-executor.service'

import { InternalFetchService } from './internal-fetch'

jest.mock('~/cdp/services/hog-executor.service', () => ({
    cdpTrackedFetch: jest.fn(),
}))

describe('InternalFetchService', () => {
    it('calls cdpTrackedFetch with internal auth header and templateId', async () => {
        const internalFetchService = new InternalFetchService({ INTERNAL_API_SECRET: 'secret-123' })
        const mockedCdpTrackedFetch = jest.mocked(cdpTrackedFetch)

        mockedCdpTrackedFetch.mockResolvedValueOnce({
            fetchError: null,
            fetchResponse: { status: 200 } as any,
            fetchDuration: 12,
        })

        await internalFetchService.fetch({
            url: 'https://internal.example.com/health',
            fetchParams: { method: 'POST', headers: { 'X-Test': 'abc' } } as any,
        })

        expect(mockedCdpTrackedFetch).toHaveBeenCalledTimes(1)
        expect(mockedCdpTrackedFetch.mock.calls[0][0]).toMatchObject({
            url: 'https://internal.example.com/health',
            templateId: 'InternalFetchService',
            fetchParams: {
                method: 'POST',
                headers: {
                    'X-Test': 'abc',
                    [INTERNAL_SERVICE_CALL_HEADER_NAME]: 'secret-123',
                },
            },
        })
    })

    it('rethrows exceptions from cdpTrackedFetch', async () => {
        const internalFetchService = new InternalFetchService({ INTERNAL_API_SECRET: 'secret-123' })
        const mockedCdpTrackedFetch = jest.mocked(cdpTrackedFetch)

        mockedCdpTrackedFetch.mockRejectedValueOnce(new Error('boom'))

        await expect(
            internalFetchService.fetch({
                url: 'https://internal.example.com/boom',
                fetchParams: { method: 'GET' } as any,
            })
        ).rejects.toThrow('boom')
    })
})
