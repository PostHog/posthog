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

        it('throws retriable error on 5xx errors', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 500,
                text: () => Promise.resolve('Internal Server Error'),
            })

            try {
                await client.processExceptions(requests)
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 500')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws retriable error on 429 rate limit errors', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 429,
                text: () => Promise.resolve('Too Many Requests'),
            })

            try {
                await client.processExceptions(requests)
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 429')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws non-retriable error on 4xx errors (except 429)', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 400,
                text: () => Promise.resolve('Bad Request'),
            })

            try {
                await client.processExceptions(requests)
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 400')
                expect(error.isRetriable).toBe(false)
            }
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

        it('throws when response is not an array', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve({ error: 'unexpected error format' }),
            })

            await expect(client.processExceptions(requests)).rejects.toThrow('Invalid Cymbal response')
        })

        it('throws when response element has invalid structure', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([{ invalid: 'no uuid field' }]),
            })

            await expect(client.processExceptions(requests)).rejects.toThrow('Invalid Cymbal response')
        })

        it('accepts null elements in response array', async () => {
            const requests = [createRequest(), createRequest()]
            const responses = [createResponse(), null] // Second event suppressed

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(requests)

            expect(results).toEqual(responses)
            expect(results[1]).toBeNull()
        })

        it('throws retriable error on network errors', async () => {
            const requests = [createRequest()]

            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            try {
                await client.processExceptions(requests)
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Network error')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws retriable error on timeout', async () => {
            const requests = [createRequest()]

            const timeoutError = new Error('Timeout')
            timeoutError.name = 'TimeoutError'

            mockFetch.mockRejectedValueOnce(timeoutError)

            try {
                await client.processExceptions(requests)
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Timeout')
                expect(error.isRetriable).toBe(true)
            }
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
