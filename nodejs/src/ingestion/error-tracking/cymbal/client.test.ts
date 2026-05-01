import { parseJSON } from '~/utils/json-parse'

import { CymbalClient, DnsResolveFunction, FetchFunction } from './client'
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

    /** Create a client with a single-IP DNS response (no sticky routing). */
    const createClient = (fetchMock: jest.Mock = mockFetch) => {
        return new CymbalClient({
            baseUrl: 'http://cymbal.example.com:8080',
            timeoutMs: 5000,
            maxBodyBytes: 1_800_000,
            fetch: fetchMock as FetchFunction,
            dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
        })
    }

    /** Create a client whose DNS returns multiple pod IPs (sticky routing active). */
    const createRoutedClient = (
        pods: string[] = ['10.0.0.1', '10.0.0.2', '10.0.0.3'],
        fetchMock: jest.Mock = mockFetch
    ) => {
        return new CymbalClient({
            baseUrl: 'http://cymbal.example.com:8080',
            timeoutMs: 5000,
            maxBodyBytes: 1_800_000,
            fetch: fetchMock as FetchFunction,
            dnsResolve: jest.fn().mockResolvedValue(pods) as DnsResolveFunction,
        })
    }

    beforeEach(() => {
        mockFetch = jest.fn()
    })

    afterEach(() => {
        jest.resetAllMocks()
    })

    describe('processExceptions', () => {
        it('returns empty array for empty input', async () => {
            const client = createClient()
            const results = await client.processExceptions([])
            expect(results).toEqual([])
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('processes a batch of exceptions successfully', async () => {
            const client = createClient()
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
                'http://1.2.3.4:8080/process',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requests),
                    timeoutMs: 5000,
                })
            )
        })

        it('handles null responses (suppressed events)', async () => {
            const client = createClient()
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
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 500,
                text: () => Promise.resolve('Internal Server Error'),
            })

            try {
                await client.processExceptions(toItems([createRequest()]))
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 500')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws retriable error on 429 rate limit errors', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 429,
                text: () => Promise.resolve('Too Many Requests'),
            })

            try {
                await client.processExceptions(toItems([createRequest()]))
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 429')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws non-retriable error on 4xx errors (except 429)', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 400,
                text: () => Promise.resolve('Bad Request'),
            })

            try {
                await client.processExceptions(toItems([createRequest()]))
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Cymbal returned 400')
                expect(error.isRetriable).toBe(false)
            }
        })

        it('throws on response length mismatch', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([createResponse()]),
            })

            await expect(client.processExceptions(toItems([createRequest(), createRequest()]))).rejects.toThrow(
                'Cymbal response length mismatch: got 1, expected 2'
            )
        })

        it('throws when response is not an array', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve({ error: 'unexpected error format' }),
            })

            await expect(client.processExceptions(toItems([createRequest()]))).rejects.toThrow(
                'Invalid Cymbal response'
            )
        })

        it('throws when response element has invalid structure', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([{ invalid: 'no uuid field' }]),
            })

            await expect(client.processExceptions(toItems([createRequest()]))).rejects.toThrow(
                'Invalid Cymbal response'
            )
        })

        it('accepts null elements in response array', async () => {
            const client = createClient()
            const requests = [createRequest(), createRequest()]
            const responses = [createResponse(), null]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve(responses),
            })

            const results = await client.processExceptions(toItems(requests))
            expect(results).toEqual(responses)
            expect(results[1]).toBeNull()
        })

        it('throws retriable error on network errors', async () => {
            const client = createClient()
            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            try {
                await client.processExceptions(toItems([createRequest()]))
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Network error')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('throws retriable error on timeout', async () => {
            const client = createClient()
            const timeoutError = new Error('Timeout')
            timeoutError.name = 'TimeoutError'
            mockFetch.mockRejectedValueOnce(timeoutError)

            try {
                await client.processExceptions(toItems([createRequest()]))
                fail('Expected error to be thrown')
            } catch (error: any) {
                expect(error.message).toContain('Timeout')
                expect(error.isRetriable).toBe(true)
            }
        })

        it('propagates DNS errors', async () => {
            const client = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 1_800_000,
                fetch: mockFetch as FetchFunction,
                dnsResolve: jest.fn().mockRejectedValue(new Error('DNS failed')) as DnsResolveFunction,
            })

            await expect(client.processExceptions(toItems([createRequest()]))).rejects.toThrow('DNS failed')
            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('size-based chunking', () => {
        it('sends a single request when total size is under the limit', async () => {
            const client = createClient()
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
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 150,
                fetch: mockFetch as FetchFunction,
                dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
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

            const results = await smallClient.processExceptions(toItems(requests, 100))
            expect(results).toHaveLength(3)
            expect(results.map((r) => r!.uuid)).toEqual(['uuid-1', 'uuid-2', 'uuid-3'])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('preserves 1:1 position correspondence across chunks', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 500,
                fetch: mockFetch as FetchFunction,
                dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
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

            const results = await smallClient.processExceptions(toItems(requests, 200))
            expect(results.map((r) => r!.uuid)).toEqual(['uuid-0', 'uuid-1', 'uuid-2', 'uuid-3', 'uuid-4'])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('puts a single oversized request in its own chunk', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 50,
                fetch: mockFetch as FetchFunction,
                dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
            })

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(responses),
                })
            })

            const results = await smallClient.processExceptions(
                toItems([createRequest({ uuid: 'uuid-1' }), createRequest({ uuid: 'uuid-2' })], 100)
            )
            expect(results).toHaveLength(2)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('aborts remaining chunks if one fails', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 150,
                fetch: mockFetch as FetchFunction,
                dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
            })

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

            const requests = [
                createRequest({ uuid: 'uuid-1' }),
                createRequest({ uuid: 'uuid-2' }),
                createRequest({ uuid: 'uuid-3' }),
            ]
            await expect(smallClient.processExceptions(toItems(requests, 100))).rejects.toThrow('Cymbal returned 500')
        })
    })

    describe('sticky routing', () => {
        it('routes events from the same team to the same pod', async () => {
            const client = createRoutedClient()

            const requests = [
                createRequest({ uuid: 'uuid-1', team_id: 42 }),
                createRequest({ uuid: 'uuid-2', team_id: 42 }),
                createRequest({ uuid: 'uuid-3', team_id: 42 }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) =>
                    createResponse({ uuid: req.uuid, team_id: req.team_id })
                )
                return Promise.resolve({ status: 200, json: () => Promise.resolve(responses) })
            })

            await client.processExceptions(toItems(requests))

            // All events from the same team go to a single pod
            expect(mockFetch).toHaveBeenCalledTimes(1)
            const url = mockFetch.mock.calls[0][0] as string
            expect(url).toMatch(/^http:\/\/10\.0\.0\.\d+:8080\/process$/)
        })

        it('coalesces teams that hash to the same pod into one HTTP call', async () => {
            const client = createRoutedClient()

            // Teams 1 and 3 hash to the same pod (index 1), team 2 hashes to a different pod (index 0)
            const requests = [
                createRequest({ uuid: 'uuid-a', team_id: 1 }),
                createRequest({ uuid: 'uuid-b', team_id: 2 }),
                createRequest({ uuid: 'uuid-c', team_id: 3 }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) =>
                    createResponse({ uuid: req.uuid, team_id: req.team_id })
                )
                return Promise.resolve({ status: 200, json: () => Promise.resolve(responses) })
            })

            const results = await client.processExceptions(toItems(requests))

            // 2 HTTP calls (one per pod), not 3 (one per team)
            expect(mockFetch).toHaveBeenCalledTimes(2)

            // The call to pod index 1 should contain both team 1 and team 3 events
            const callBodies = mockFetch.mock.calls.map((call) => parseJSON(call[1].body))
            const twoEventCall = callBodies.find((body: CymbalRequest[]) => body.length === 2)
            expect(twoEventCall).toBeDefined()
            expect(twoEventCall!.map((r: CymbalRequest) => r.team_id)).toEqual([1, 3])

            // Results still maintain 1:1 position correspondence
            expect(results.map((r) => r!.uuid)).toEqual(['uuid-a', 'uuid-b', 'uuid-c'])
        })

        it('routes events from different teams to potentially different pods in parallel', async () => {
            const client = createRoutedClient()

            const requests = [
                createRequest({ uuid: 'uuid-1', team_id: 1 }),
                createRequest({ uuid: 'uuid-2', team_id: 2 }),
                createRequest({ uuid: 'uuid-3', team_id: 3 }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) =>
                    createResponse({ uuid: req.uuid, team_id: req.team_id })
                )
                return Promise.resolve({ status: 200, json: () => Promise.resolve(responses) })
            })

            await client.processExceptions(toItems(requests))

            const urls = mockFetch.mock.calls.map((call) => call[0] as string)
            urls.forEach((url) => expect(url).toMatch(/^http:\/\/10\.0\.0\.\d+:8080\/process$/))
        })

        it('preserves 1:1 position correspondence with mixed teams', async () => {
            const client = createRoutedClient()

            // Interleaved team IDs
            const requests = [
                createRequest({ uuid: 'uuid-a', team_id: 1 }),
                createRequest({ uuid: 'uuid-b', team_id: 2 }),
                createRequest({ uuid: 'uuid-c', team_id: 1 }),
                createRequest({ uuid: 'uuid-d', team_id: 3 }),
                createRequest({ uuid: 'uuid-e', team_id: 2 }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) =>
                    createResponse({ uuid: req.uuid, team_id: req.team_id })
                )
                return Promise.resolve({ status: 200, json: () => Promise.resolve(responses) })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results.map((r) => r!.uuid)).toEqual(['uuid-a', 'uuid-b', 'uuid-c', 'uuid-d', 'uuid-e'])
            expect(results.map((r) => r!.team_id)).toEqual([1, 2, 1, 3, 2])
        })

        it('routes consistently for the same team_id', async () => {
            const client = createRoutedClient()

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))),
                })
            })

            for (let i = 0; i < 5; i++) {
                await client.processExceptions(toItems([createRequest({ uuid: `uuid-${i}`, team_id: 99 })]))
            }

            const urls = mockFetch.mock.calls.map((call) => call[0] as string)
            expect(new Set(urls).size).toBe(1)
        })

        it('skips grouping when DNS returns a single IP', async () => {
            const client = createRoutedClient(['10.0.0.1'])

            const requests = [
                createRequest({ uuid: 'uuid-1', team_id: 1 }),
                createRequest({ uuid: 'uuid-2', team_id: 2 }),
            ]

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({ status: 200, json: () => Promise.resolve(responses) })
            })

            await client.processExceptions(toItems(requests))

            // Single endpoint — no grouping, single HTTP call with both events
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith('http://10.0.0.1:8080/process', expect.any(Object))
        })
    })

    describe('healthCheck', () => {
        it('returns true when health check succeeds', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 200 })

            const result = await client.healthCheck()

            expect(result).toBe(true)
            expect(mockFetch).toHaveBeenCalledWith(
                'http://cymbal.example.com:8080/_liveness',
                // Health check uses the hostname directly
                expect.objectContaining({ method: 'GET' })
            )
        })

        it('returns false when health check fails', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 503 })
            expect(await client.healthCheck()).toBe(false)
        })

        it('returns false on network error', async () => {
            const client = createClient()
            mockFetch.mockRejectedValueOnce(new Error('Network error'))
            expect(await client.healthCheck()).toBe(false)
        })
    })
})
