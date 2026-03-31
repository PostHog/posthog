import { parseJSON } from '~/utils/json-parse'

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

/** Wrap requests into items with a default size estimate (small enough that batches never split). */
const toItems = (requests: CymbalRequest[], size = 100) => requests.map((request) => ({ request, estimatedSize: size }))

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
            maxBodyBytes: 1_800_000,
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

            const results = await client.processExceptions(toItems(requests))

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

            const results = await client.processExceptions(toItems(requests))

            expect(results).toEqual([null])
        })

        it('throws retriable error on 5xx errors', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 500,
                text: () => Promise.resolve('Internal Server Error'),
            })

            try {
                await client.processExceptions(toItems(requests))
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
                await client.processExceptions(toItems(requests))
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
                await client.processExceptions(toItems(requests))
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

            await expect(client.processExceptions(toItems(requests))).rejects.toThrow(
                'Cymbal response length mismatch: got 1, expected 2'
            )
        })

        it('throws when response is not an array', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve({ error: 'unexpected error format' }),
            })

            await expect(client.processExceptions(toItems(requests))).rejects.toThrow('Invalid Cymbal response')
        })

        it('throws when response element has invalid structure', async () => {
            const requests = [createRequest()]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([{ invalid: 'no uuid field' }]),
            })

            await expect(client.processExceptions(toItems(requests))).rejects.toThrow('Invalid Cymbal response')
        })

        it('accepts null elements in response array', async () => {
            const requests = [createRequest(), createRequest()]
            const responses = [createResponse(), null] // Second event suppressed

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toEqual(responses)
            expect(results[1]).toBeNull()
        })

        it('throws retriable error on network errors', async () => {
            const requests = [createRequest()]

            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            try {
                await client.processExceptions(toItems(requests))
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
                await client.processExceptions(toItems(requests))
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
                maxBodyBytes: 1_800_000,
                fetch: mockFetch as FetchFunction,
            })

            const responses = [createResponse()]
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            await clientWithTrailingSlash.processExceptions(toItems([createRequest()]))

            expect(mockFetch).toHaveBeenCalledWith('http://cymbal.example.com/process', expect.any(Object))
        })
    })

    describe('size-based chunking', () => {
        it('sends a single request when total size is under the limit', async () => {
            const requests = [createRequest({ uuid: 'uuid-1' }), createRequest({ uuid: 'uuid-2' })]
            const responses = [createResponse({ uuid: 'uuid-1' }), createResponse({ uuid: 'uuid-2' })]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('splits into multiple requests when total size exceeds the limit', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com',
                timeoutMs: 5000,
                maxBodyBytes: 150,
                fetch: mockFetch as FetchFunction,
            })

            const requests = [
                createRequest({ uuid: 'uuid-1' }),
                createRequest({ uuid: 'uuid-2' }),
                createRequest({ uuid: 'uuid-3' }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(responses),
                })
            })

            // Each request is estimated at 100 bytes, limit is 150 — so max 1 per chunk
            const results = await smallClient.processExceptions(toItems(requests, 100))

            expect(results).toHaveLength(3)
            expect(results.map((r) => r!.uuid)).toEqual(['uuid-1', 'uuid-2', 'uuid-3'])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('preserves 1:1 position correspondence across chunks', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com',
                timeoutMs: 5000,
                maxBodyBytes: 500,
                fetch: mockFetch as FetchFunction,
            })

            const requests = Array.from({ length: 5 }, (_, i) => createRequest({ uuid: `uuid-${i}` }))
            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(responses),
                })
            })

            // 200 bytes each, limit 500 — chunks of 2, 2, 1
            const results = await smallClient.processExceptions(toItems(requests, 200))

            expect(results.map((r) => r!.uuid)).toEqual(['uuid-0', 'uuid-1', 'uuid-2', 'uuid-3', 'uuid-4'])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('puts a single oversized request in its own chunk', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com',
                timeoutMs: 5000,
                maxBodyBytes: 50,
                fetch: mockFetch as FetchFunction,
            })

            const requests = [createRequest({ uuid: 'uuid-1' }), createRequest({ uuid: 'uuid-2' })]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(responses),
                })
            })

            // Each request is 100 bytes, limit is 50 — each gets its own chunk
            const results = await smallClient.processExceptions(toItems(requests, 100))

            expect(results).toHaveLength(2)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('aborts remaining chunks if one fails', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com',
                timeoutMs: 5000,
                maxBodyBytes: 150,
                fetch: mockFetch as FetchFunction,
            })

            const requests = [
                createRequest({ uuid: 'uuid-1' }),
                createRequest({ uuid: 'uuid-2' }),
                createRequest({ uuid: 'uuid-3' }),
            ]

            let callCount = 0
            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                callCount++
                if (callCount === 1) {
                    const parsed = parseJSON(options.body)
                    return Promise.resolve({
                        status: 200,
                        json: () => Promise.resolve(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                    })
                }
                return Promise.resolve({ status: 500, text: () => Promise.resolve('Internal Server Error') })
            })

            await expect(smallClient.processExceptions(toItems(requests, 100))).rejects.toThrow('Cymbal returned 500')
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
