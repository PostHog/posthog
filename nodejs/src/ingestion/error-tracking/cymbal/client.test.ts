import { parseJSON } from '~/utils/json-parse'

import { CymbalClient, CymbalEventResult, FetchFunction } from './client'
import { CymbalRequest, CymbalResponse } from './types'

/** Extract the CymbalResponse from a successful result, or fail. */
function unwrapSuccess(result: CymbalEventResult): CymbalResponse | null {
    expect(result.status).toBe('success')
    if (result.status !== 'success') {
        throw new Error(`Expected success, got ${result.status}`)
    }
    return result.response
}

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

    const createClient = (fetchMock: jest.Mock = mockFetch) => {
        return new CymbalClient({
            baseUrl: 'http://cymbal.example.com:8080',
            timeoutMs: 5000,
            maxBodyBytes: 1_800_000,
            fetch: fetchMock as FetchFunction,
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

            expect(results.map((r) => unwrapSuccess(r))).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith(
                'http://cymbal.example.com:8080/process',
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

            expect(unwrapSuccess(results[0])).toBeNull()
        })

        it('returns retriable failed on 5xx errors', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 500, json: () => Promise.resolve({}) })

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(true)
            }
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('returns retriable failed on 429 rate limit errors', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 429, json: () => Promise.resolve({}) })

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(true)
            }
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('returns non-retriable failed result on 4xx errors (except 429)', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 400, json: () => Promise.resolve({}) })

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(false)
                expect(results[0].reason).toContain('Cymbal returned 400')
            }
        })

        it('returns non-retriable failed result on response length mismatch', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([createResponse()]),
            })

            const results = await client.processExceptions(toItems([createRequest(), createRequest()]))
            expect(results).toHaveLength(2)
            for (const result of results) {
                expect(result.status).toBe('failed')
                if (result.status === 'failed') {
                    expect(result.retriable).toBe(false)
                    expect(result.reason).toContain('length mismatch')
                }
            }
        })

        it('returns non-retriable failed result when response is not an array', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve({ error: 'unexpected error format' }),
            })

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(false)
                expect(results[0].reason).toContain('Invalid Cymbal response')
            }
        })

        it('returns non-retriable failed result when response element has invalid structure', async () => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({
                status: 200,
                json: () => Promise.resolve([{ invalid: 'no uuid field' }]),
            })

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(false)
                expect(results[0].reason).toContain('Invalid Cymbal response')
            }
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
            expect(unwrapSuccess(results[0])).toEqual(responses[0])
            expect(unwrapSuccess(results[1])).toBeNull()
        })

        it('returns retriable failed on network errors', async () => {
            const client = createClient()
            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(true)
                expect(results[0].reason).toContain('Network error')
            }
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('returns retriable failed on timeout', async () => {
            const client = createClient()
            mockFetch.mockRejectedValueOnce(new Error('The operation was aborted due to timeout'))

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            if (results[0].status === 'failed') {
                expect(results[0].retriable).toBe(true)
            }
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('does not retry — retries are handled by the pipeline wrapper', async () => {
            const client = createClient()
            // First call fails — client returns failed, does NOT retry
            mockFetch.mockRejectedValueOnce(new Error('Network error'))

            const results = await client.processExceptions(toItems([createRequest()]))
            expect(results).toHaveLength(1)
            expect(results[0].status).toBe('failed')
            // Only 1 call — no retry
            expect(mockFetch).toHaveBeenCalledTimes(1)
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
            expect(results.map((r) => unwrapSuccess(r))).toEqual(responses)
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('splits into multiple requests when total size exceeds the limit', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
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

            const results = await smallClient.processExceptions(toItems(requests, 100))
            expect(results).toHaveLength(3)
            expect(results.map((r) => unwrapSuccess(r)!.uuid)).toEqual(['uuid-1', 'uuid-2', 'uuid-3'])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('preserves 1:1 position correspondence across chunks', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
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

            const results = await smallClient.processExceptions(toItems(requests, 200))
            expect(results.map((r) => unwrapSuccess(r)!.uuid)).toEqual([
                'uuid-0',
                'uuid-1',
                'uuid-2',
                'uuid-3',
                'uuid-4',
            ])
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('puts a single oversized request in its own chunk', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 50,

                fetch: mockFetch as FetchFunction,
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

        it('returns failed for all events in group when chunk returns 5xx', async () => {
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 150,

                fetch: mockFetch as FetchFunction,
            })

            // All calls return 500
            mockFetch.mockResolvedValue({ status: 500, json: () => Promise.resolve({}) })

            const requests = [
                createRequest({ uuid: 'uuid-1' }),
                createRequest({ uuid: 'uuid-2' }),
                createRequest({ uuid: 'uuid-3' }),
            ]
            const results = await smallClient.processExceptions(toItems(requests, 100))
            expect(results).toHaveLength(3)
            expect(results.every((r) => r.status === 'failed')).toBe(true)
            expect(results.every((r) => r.status === 'failed' && r.retriable)).toBe(true)
        })
    })

    describe('fan-out and per-event isolation', () => {
        const createTimeoutError = () => {
            const error = new Error('The operation was aborted due to timeout')
            error.name = 'TimeoutError'
            return error
        }

        it('fans out on timeout and marks the offending event retriable for the wrapper', async () => {
            const client = createClient()
            const requests = [
                createRequest({ uuid: 'good-1' }),
                createRequest({ uuid: 'good-2' }),
                createRequest({ uuid: 'poison' }),
                createRequest({ uuid: 'good-3' }),
            ]

            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                const hasPoison = parsed.some((r: CymbalRequest) => r.uuid === 'poison')
                if (hasPoison) {
                    return Promise.reject(createTimeoutError())
                }
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toHaveLength(4)
            expect(unwrapSuccess(results[0])).toMatchObject({ uuid: 'good-1' })
            expect(unwrapSuccess(results[1])).toMatchObject({ uuid: 'good-2' })
            // Offending event → retriable failure; wrapper routes per its
            // overflowEnabled flag (overflow on main lane, DLQ on overflow lane).
            expect(results[2]).toMatchObject({
                status: 'failed',
                retriable: true,
                reason: expect.stringContaining('timeout'),
            })
            expect(unwrapSuccess(results[3])).toMatchObject({ uuid: 'good-3' })
        })

        it('fans out on 500 to isolate single-event-triggered server errors', async () => {
            const client = createClient()
            const requests = [
                createRequest({ uuid: 'good-1' }),
                createRequest({ uuid: 'bad' }),
                createRequest({ uuid: 'good-2' }),
            ]

            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                const hasBad = parsed.some((r: CymbalRequest) => r.uuid === 'bad')
                if (hasBad) {
                    return Promise.resolve({ status: 500, json: () => Promise.resolve({}) })
                }
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toHaveLength(3)
            expect(unwrapSuccess(results[0])).toMatchObject({ uuid: 'good-1' })
            expect(results[1]).toMatchObject({
                status: 'failed',
                retriable: true,
                reason: expect.stringContaining('500'),
            })
            expect(unwrapSuccess(results[2])).toMatchObject({ uuid: 'good-2' })
        })

        it('does not fan out on 429 — backpressure propagates as whole-chunk retriable', async () => {
            const client = createClient()
            const requests = [createRequest({ uuid: 'a' }), createRequest({ uuid: 'b' })]

            mockFetch.mockResolvedValue({ status: 429, json: () => Promise.resolve({}) })

            const results = await client.processExceptions(toItems(requests))

            // 429 = explicit backpressure. Fanning out would amplify load
            // against an already-overloaded service. The chunk fails as a
            // whole and the wrapper retries with its backoff policy.
            expect(results).toHaveLength(2)
            for (const r of results) {
                expect(r).toMatchObject({
                    status: 'failed',
                    retriable: true,
                    reason: expect.stringContaining('429'),
                })
            }
            // Exactly one call — no per-event fan-out probing.
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('keeps successful peers from a fan-out attempt — never throws away progress', async () => {
            const client = createClient()
            const requests = [
                createRequest({ uuid: 'good-1' }),
                createRequest({ uuid: 'good-2' }),
                createRequest({ uuid: 'poison' }),
            ]

            let callCount = 0
            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                callCount++
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                if (callCount === 1) {
                    // Initial chunk call: times out (poison present), triggers fan-out.
                    return Promise.reject(createTimeoutError())
                }
                // Per-event fan-out calls: poison times out individually; others succeed.
                if (parsed[0].uuid === 'poison') {
                    return Promise.reject(createTimeoutError())
                }
                return Promise.resolve({
                    status: 200,
                    json: () => Promise.resolve([createResponse({ uuid: parsed[0].uuid })]),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toHaveLength(3)
            expect(unwrapSuccess(results[0])).toMatchObject({ uuid: 'good-1' })
            expect(unwrapSuccess(results[1])).toMatchObject({ uuid: 'good-2' })
            expect(results[2]).toMatchObject({ status: 'failed', retriable: true })
        })

        it('preserves successful chunks when a later chunk fails without fan-out', async () => {
            // Two chunks (size budget forces one event per chunk). First
            // succeeds, second returns 429 (no fan-out for backpressure).
            // The first chunk's success must be preserved; the failure
            // verdict must apply only to the failing chunk's event so the
            // wrapper can retry it targetedly rather than re-running the
            // already-successful event.
            const smallClient = new CymbalClient({
                baseUrl: 'http://cymbal.example.com:8080',
                timeoutMs: 5000,
                maxBodyBytes: 150,
                fetch: mockFetch as FetchFunction,
            })

            let callCount = 0
            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                callCount++
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                if (callCount === 1) {
                    return Promise.resolve({
                        status: 200,
                        json: () => Promise.resolve(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                    })
                }
                return Promise.resolve({ status: 429, json: () => Promise.resolve({}) })
            })

            const results = await smallClient.processExceptions(
                toItems([createRequest({ uuid: 'good' }), createRequest({ uuid: 'bad' })], 100)
            )

            expect(results).toHaveLength(2)
            expect(unwrapSuccess(results[0])).toMatchObject({ uuid: 'good' })
            expect(results[1]).toMatchObject({
                status: 'failed',
                retriable: true,
                reason: expect.stringContaining('429'),
            })
        })

        it('does not fan out single-event chunks — surfaces as retriable failure', async () => {
            const client = createClient()
            mockFetch.mockRejectedValue(createTimeoutError())

            const [result] = await client.processExceptions(toItems([createRequest()]))
            expect(result).toMatchObject({
                status: 'failed',
                retriable: true,
                reason: expect.any(String),
            })
        })
    })
})
