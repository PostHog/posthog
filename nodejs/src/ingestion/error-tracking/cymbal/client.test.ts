import { CymbalClient, FetchFunction } from './client'
import { CymbalRequest, CymbalResponse } from './types'

// Suppress logger output during tests
jest.mock('~/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

describe('CymbalClient', () => {
    let client: CymbalClient
    let mockFetch: jest.Mock

    const createRequest = (overrides: Partial<CymbalRequest> = {}): CymbalRequest => ({
        uuid: 'test-uuid',
        event: '$exception',
        team_id: 1,
        timestamp: '2024-01-01T00:00:00Z',
        properties: { $exception_list: [{ type: 'Error', value: 'Test error' }] },
        ...overrides,
    })

    const createResponse = (overrides: Partial<CymbalResponse> = {}): CymbalResponse => ({
        uuid: 'test-uuid',
        event: '$exception',
        team_id: 1,
        timestamp: '2024-01-01T00:00:00Z',
        properties: {
            $exception_list: [{ type: 'Error', value: 'Test error' }],
            $exception_fingerprint: 'test-fingerprint',
            $exception_issue_id: 'test-issue-id',
        },
        ...overrides,
    })

    const createClient = (fetchMock: jest.Mock = mockFetch) => {
        return new CymbalClient({
            baseUrl: 'http://cymbal.example.com',
            timeoutMs: 5000,
            maxRetries: 3,
            fetch: fetchMock as FetchFunction,
        })
    }

    beforeEach(() => {
        mockFetch = jest.fn()
        client = createClient()
    })

    afterEach(() => {
        jest.resetAllMocks()
    })

    describe('processExceptions', () => {
        it('returns empty array for empty input', async () => {
            const results = await client.processExceptions([])
            expect(results).toEqual([])
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('processes a batch of exceptions successfully', async () => {
            const requests = [createRequest({ uuid: 'uuid-1' }), createRequest({ uuid: 'uuid-2' })]
            const responses = [
                createResponse({ uuid: 'uuid-1', properties: { $exception_fingerprint: 'fp-1' } }),
                createResponse({ uuid: 'uuid-2', properties: { $exception_fingerprint: 'fp-2' } }),
            ]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith(
                'http://cymbal.example.com/process',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requests),
                    timeoutMs: 5000,
                })
            )
        })

        it('handles null responses (suppressed events)', async () => {
            const requests = [createRequest()]
            const responses = [null]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(requests)

            expect(results).toEqual([null])
        })

        it('retries on 5xx errors', async () => {
            const requests = [createRequest()]
            const responses = [createResponse()]

            mockFetch
                .mockResolvedValueOnce({
                    ok: false,
                    status: 500,
                    text: () => Promise.resolve('Internal Server Error'),
                })
                .mockResolvedValueOnce({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve(responses),
                })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('retries on 429 rate limit errors', async () => {
            const requests = [createRequest()]
            const responses = [createResponse()]

            mockFetch
                .mockResolvedValueOnce({
                    ok: false,
                    status: 429,
                    text: () => Promise.resolve('Too Many Requests'),
                })
                .mockResolvedValueOnce({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve(responses),
                })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('does not retry on 4xx errors (except 429)', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 400,
                text: () => Promise.resolve('Bad Request'),
            })

            await expect(client.processExceptions(requests)).rejects.toThrow('Cymbal returned 400: Bad Request')
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('throws on response length mismatch', async () => {
            const requests = [createRequest(), createRequest()]
            const responses = [createResponse()] // Only one response for two requests

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            await expect(client.processExceptions(requests)).rejects.toThrow(
                'Cymbal response length mismatch: got 1, expected 2'
            )
        })

        it('retries on network errors', async () => {
            const requests = [createRequest()]
            const responses = [createResponse()]

            mockFetch.mockRejectedValueOnce(new Error('Network error')).mockResolvedValueOnce({
                ok: true,
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('retries on timeout (TimeoutError)', async () => {
            const requests = [createRequest()]
            const responses = [createResponse()]

            const timeoutError = new Error('Timeout')
            timeoutError.name = 'TimeoutError'

            mockFetch.mockRejectedValueOnce(timeoutError).mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('exhausts retries and throws', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValue({
                status: 500,
                text: () => Promise.resolve('Internal Server Error'),
            })

            // maxRetries is 3, meaning 3 total attempts
            await expect(client.processExceptions(requests)).rejects.toThrow('Cymbal returned 500')
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('removes trailing slash from baseUrl', async () => {
            const clientWithTrailingSlash = new CymbalClient({
                baseUrl: 'http://cymbal.example.com/',
                timeoutMs: 5000,
                fetch: mockFetch as FetchFunction,
            })

            const responses = [createResponse()]
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            await clientWithTrailingSlash.processExceptions([createRequest()])

            expect(mockFetch).toHaveBeenCalledWith('http://cymbal.example.com/process', expect.any(Object))
        })
    })

    describe('healthCheck', () => {
        it('returns true when health check succeeds', async () => {
            mockFetch.mockResolvedValueOnce({
                status: 200,
            })

            const result = await client.healthCheck()

            expect(result).toBe(true)
            expect(mockFetch).toHaveBeenCalledWith(
                'http://cymbal.example.com/_liveness',
                expect.objectContaining({
                    method: 'GET',
                })
            )
        })

        it('returns false when health check fails', async () => {
            mockFetch.mockResolvedValueOnce({
                status: 503,
            })

            const result = await client.healthCheck()

            expect(result).toBe(false)
        })

        it('returns false on network error', async () => {
            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            const result = await client.healthCheck()

            expect(result).toBe(false)
        })
    })
})
