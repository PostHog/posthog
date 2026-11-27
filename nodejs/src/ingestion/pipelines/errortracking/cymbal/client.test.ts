import { parseJSON } from '~/common/utils/json-parse'

import { CymbalClient, CymbalResult, DnsResolveFunction, FetchFunction } from './client'
import { CymbalRequest, CymbalResponse } from './types'

// Suppress logger output during tests
jest.mock('~/common/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

const ITEM_RESULTS_HEADERS = { 'x-posthog-ingestion-response': '1' }

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

    const toOutcomes = (responses: (CymbalResponse | null)[]): CymbalResult[] =>
        responses.map((response) =>
            response ? { result: 'ok', value: response } : { result: 'drop', reason: 'suppressed' }
        )

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
                headers: ITEM_RESULTS_HEADERS,
                json: () => Promise.resolve({ results: toOutcomes(responses) }),
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toEqual(toOutcomes(responses))
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith(
                'http://1.2.3.4:8080/process',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'x-posthog-ingestion-response': '1' },
                    body: JSON.stringify(requests),
                    timeoutMs: 5000,
                })
            )
        })

        it('returns drop and fail results without throwing', async () => {
            const client = createClient()
            const results: CymbalResult[] = [
                { result: 'drop', reason: 'rate_limited_project' },
                { result: 'fail', error: { code: 'invalid_input', message: 'boom' } },
            ]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                headers: ITEM_RESULTS_HEADERS,
                json: () => Promise.resolve({ results }),
            })

            await expect(client.processExceptions(toItems([createRequest(), createRequest()]))).resolves.toEqual(
                results
            )
        })

        it.each([
            [500, 'retry', 'server_error'],
            [400, 'fail', 'invalid_request'],
            [413, 'fail', 'invalid_request'],
        ])('gives each event of a %i response a %s result', async (status, result, code) => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status, text: () => Promise.resolve('error body') })

            const results = await client.processExceptions(toItems([createRequest(), createRequest()]))

            const expected = { result, error: { code, message: `Cymbal returned ${status}` } }
            expect(results).toEqual([expected, expected])
        })

        it.each([
            [
                'a result count that does not match',
                () => Promise.resolve({ results: toOutcomes([createResponse()]) }),
                'Item results length mismatch: got 1, expected 2',
            ],
            [
                'a body without item results',
                () => Promise.resolve({ error: 'unexpected error format' }),
                'Invalid item results',
            ],
            [
                'a result with an invalid value',
                () =>
                    Promise.resolve({
                        results: [
                            { result: 'ok', value: { invalid: 'no uuid field' } },
                            ...toOutcomes([createResponse()]),
                        ],
                    }),
                'Invalid item results',
            ],
            [
                'a body that is not JSON',
                () => Promise.reject(new SyntaxError('Unexpected token < in JSON')),
                'Invalid Cymbal response body',
            ],
        ])('fails each event of a response with %s', async (_name, json, message) => {
            const client = createClient()
            mockFetch.mockResolvedValueOnce({ status: 200, headers: ITEM_RESULTS_HEADERS, json })

            const results = await client.processExceptions(toItems([createRequest(), createRequest()]))

            const expected = {
                result: 'fail',
                error: { code: 'invalid_response', message: expect.stringContaining(message) },
            }
            expect(results).toEqual([expected, expected])
        })

        it('accepts null elements in response array', async () => {
            const client = createClient()
            const requests = [createRequest(), createRequest()]
            const responses = [createResponse(), null]

            mockFetch.mockResolvedValueOnce({
                status: 200,
                headers: ITEM_RESULTS_HEADERS,
                json: () => Promise.resolve({ results: toOutcomes(responses) }),
            })

            const results = await client.processExceptions(toItems(requests))
            expect(results).toEqual(toOutcomes(responses))
        })

        it('reads the array that a pod without item results answers', async () => {
            const client = createClient()
            const failed = createResponse({ uuid: 'uuid-1', properties: { $cymbal_errors: ['No sourcemap found'] } })
            const processed = createResponse({ uuid: 'uuid-3' })

            mockFetch.mockResolvedValueOnce({
                status: 200,
                headers: {},
                json: () => Promise.resolve([failed, null, processed]),
            })

            const results = await client.processExceptions(toItems([createRequest(), createRequest(), createRequest()]))

            expect(results).toEqual([
                {
                    result: 'ok',
                    value: failed,
                    warnings: [
                        {
                            type: 'error_tracking_exception_processing_errors',
                            details: { eventUuid: 'uuid-1', errors: ['No sourcemap found'] },
                            key: 'uuid-1',
                        },
                    ],
                },
                { result: 'drop', reason: 'suppressed' },
                { result: 'ok', value: processed },
            ])
        })

        it('asks to retry an event whose request times out on its own', async () => {
            const client = createClient()
            const error = new Error('request timed out')
            error.name = 'TimeoutError'
            mockFetch.mockRejectedValueOnce(error)

            const results = await client.processExceptions(toItems([createRequest()]))

            expect(results).toEqual([
                { result: 'retry', error: { code: 'deadline_exceeded', message: 'request timed out' } },
            ])
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['a network error', () => Promise.reject(new Error('connect ECONNREFUSED'))],
            ['a 429', () => Promise.resolve({ status: 429 })],
            ['a 503', () => Promise.resolve({ status: 503 })],
            [
                'a body cut off by the network',
                () =>
                    Promise.resolve({
                        status: 200,
                        headers: ITEM_RESULTS_HEADERS,
                        json: () => Promise.reject(new Error('other side closed')),
                    }),
            ],
        ])('throws a retriable error so the whole batch is retried on %s', async (_name, response) => {
            const client = createClient()
            mockFetch.mockImplementationOnce(response)

            await expect(client.processExceptions(toItems([createRequest()]))).rejects.toMatchObject({
                name: 'CymbalError',
                isRetriable: true,
            })
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
                headers: ITEM_RESULTS_HEADERS,
                json: () => Promise.resolve({ results: toOutcomes(responses) }),
            })

            const results = await client.processExceptions(toItems(requests))
            expect(results).toEqual(toOutcomes(responses))
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
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
            })

            const results = await smallClient.processExceptions(toItems(requests, 100))
            expect(results).toHaveLength(3)
            expect(results.map((r) => (r.result === 'ok' ? r.value.uuid : undefined))).toEqual([
                'uuid-1',
                'uuid-2',
                'uuid-3',
            ])
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
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
            })

            const results = await smallClient.processExceptions(toItems(requests, 200))
            expect(results.map((r) => (r.result === 'ok' ? r.value.uuid : undefined))).toEqual([
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
                dnsResolve: jest.fn().mockResolvedValue(['1.2.3.4']) as DnsResolveFunction,
            })

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                const responses = parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
            })

            const results = await smallClient.processExceptions(
                toItems([createRequest({ uuid: 'uuid-1' }), createRequest({ uuid: 'uuid-2' })], 100)
            )
            expect(results).toHaveLength(2)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('keeps the results of the other chunks when one fails', async () => {
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
                        headers: ITEM_RESULTS_HEADERS,
                        json: () =>
                            Promise.resolve({
                                results: toOutcomes(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                            }),
                    })
                }
                return Promise.resolve({ status: 500, text: () => Promise.resolve('Internal Server Error') })
            })

            const requests = [
                createRequest({ uuid: 'uuid-1' }),
                createRequest({ uuid: 'uuid-2' }),
                createRequest({ uuid: 'uuid-3' }),
            ]
            const results = await smallClient.processExceptions(toItems(requests, 100))

            const retry = { result: 'retry', error: { code: 'server_error', message: 'Cymbal returned 500' } }
            expect(results).toEqual([...toOutcomes([createResponse({ uuid: 'uuid-1' })]), retry, retry])
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
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
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
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
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
            expect(results.map((r) => (r.result === 'ok' ? r.value.uuid : undefined))).toEqual([
                'uuid-a',
                'uuid-b',
                'uuid-c',
            ])
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
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
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
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results.map((r) => (r.result === 'ok' ? r.value.uuid : undefined))).toEqual([
                'uuid-a',
                'uuid-b',
                'uuid-c',
                'uuid-d',
                'uuid-e',
            ])
            expect(results.map((r) => (r.result === 'ok' ? r.value.team_id : undefined))).toEqual([1, 2, 1, 3, 2])
        })

        it('routes consistently for the same team_id', async () => {
            const client = createRoutedClient()

            mockFetch.mockImplementation((_url: string, options: { body: string }) => {
                const parsed = parseJSON(options.body)
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () =>
                        Promise.resolve({
                            results: toOutcomes(parsed.map((req: CymbalRequest) => createResponse({ uuid: req.uuid }))),
                        }),
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
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes(responses) }),
                })
            })

            await client.processExceptions(toItems(requests))

            // Single endpoint — no grouping, single HTTP call with both events
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith('http://10.0.0.1:8080/process', expect.any(Object))
        })
    })

    describe('processEachException', () => {
        const unlimited = { concurrency: 10, startBefore: Number.POSITIVE_INFINITY }

        const answerEachAlone = (statusFor: (uuid: string) => number = () => 200) =>
            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                const [request] = parseJSON(opts.body) as CymbalRequest[]
                const status = statusFor(request.uuid)
                if (status !== 200) {
                    return Promise.resolve({ status })
                }
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes([createResponse({ uuid: request.uuid })]) }),
                })
            })

        it('sends each event alone to its team pod and gives a failed one its own result', async () => {
            // Teams 1 and 3 route to 10.0.0.2 and team 2 routes to 10.0.0.1.
            const client = createRoutedClient()
            answerEachAlone((uuid) => ({ a: 200, b: 500, c: 429 })[uuid]!)

            const results = await client.processEachException(
                toItems([
                    createRequest({ uuid: 'a', team_id: 1 }),
                    createRequest({ uuid: 'b', team_id: 2 }),
                    createRequest({ uuid: 'c', team_id: 3 }),
                ]),
                unlimited
            )

            expect(results).toEqual([
                ...toOutcomes([createResponse({ uuid: 'a' })]),
                { result: 'retry', error: { code: 'server_error', message: 'Cymbal returned 500' } },
                { result: 'retry', error: { code: 'unavailable', message: 'Cymbal returned 429' } },
            ])
            const requestsSent = mockFetch.mock.calls.map(([url, opts]) => [
                url,
                (parseJSON(opts.body) as CymbalRequest[]).map((request) => request.uuid),
            ])
            expect(requestsSent).toEqual([
                ['http://10.0.0.2:8080/process', ['a']],
                ['http://10.0.0.1:8080/process', ['b']],
                ['http://10.0.0.2:8080/process', ['c']],
            ])
        })

        it('runs at most `concurrency` requests at once and starts none at or after `startBefore`', async () => {
            jest.useFakeTimers()
            try {
                const client = createClient()
                mockFetch.mockImplementation(
                    (_url: string, opts: { body: string }) =>
                        new Promise((resolve) => {
                            const [request] = parseJSON(opts.body) as CymbalRequest[]
                            const response = createResponse({ uuid: request.uuid })
                            setTimeout(
                                () =>
                                    resolve({
                                        status: 200,
                                        headers: ITEM_RESULTS_HEADERS,
                                        json: () => Promise.resolve({ results: toOutcomes([response]) }),
                                    }),
                                1_000
                            )
                        })
                )

                const pending = client.processEachException(
                    toItems(['a', 'b', 'c'].map((uuid) => createRequest({ uuid }))),
                    { concurrency: 1, startBefore: Date.now() + 1_500 }
                )
                await jest.runAllTimersAsync()

                expect(await pending).toEqual([
                    ...toOutcomes([createResponse({ uuid: 'a' }), createResponse({ uuid: 'b' })]),
                    undefined,
                ])
            } finally {
                jest.useRealTimers()
            }
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

    describe('poison pill isolation', () => {
        const createTimeoutError = () => {
            const error = new Error('The operation was aborted due to timeout')
            error.name = 'TimeoutError'
            return error
        }

        it('fans out to individual events on timeout and fails the poison pill', async () => {
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
                    headers: ITEM_RESULTS_HEADERS,
                    json: () =>
                        Promise.resolve({
                            results: toOutcomes(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                        }),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toHaveLength(4)
            expect(results[0]).toMatchObject({ value: { uuid: 'good-1' } })
            expect(results[1]).toMatchObject({ value: { uuid: 'good-2' } })
            expect(results[2]).toMatchObject({ result: 'retry', error: { code: 'deadline_exceeded' } })
            expect(results[3]).toMatchObject({ value: { uuid: 'good-3' } })
        })

        it('gives an event the result of its own request when that request fails during fan-out', async () => {
            const client = createClient()
            const requests = [createRequest({ uuid: 'a' }), createRequest({ uuid: 'b' })]

            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                if (parsed.length > 1) {
                    return Promise.reject(createTimeoutError())
                }
                if (parsed[0].uuid === 'a') {
                    return Promise.resolve({ status: 500, json: () => Promise.resolve({}) })
                }
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () => Promise.resolve({ results: toOutcomes([createResponse({ uuid: 'b' })]) }),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toEqual([
                { result: 'retry', error: { code: 'server_error', message: 'Cymbal returned 500' } },
                ...toOutcomes([createResponse({ uuid: 'b' })]),
            ])
        })

        it('preserves 1:1 ordering with poison pill at various positions', async () => {
            const client = createClient()
            const inputs = ['a', 'b', 'POISON', 'c', 'd']
            const requests = inputs.map((id) => createRequest({ uuid: id }))

            mockFetch.mockImplementation((_url: string, opts: { body: string }) => {
                const parsed = parseJSON(opts.body) as CymbalRequest[]
                if (parsed.some((r: CymbalRequest) => r.uuid === 'POISON')) {
                    return Promise.reject(createTimeoutError())
                }
                return Promise.resolve({
                    status: 200,
                    headers: ITEM_RESULTS_HEADERS,
                    json: () =>
                        Promise.resolve({
                            results: toOutcomes(parsed.map((r: CymbalRequest) => createResponse({ uuid: r.uuid }))),
                        }),
                })
            })

            const results = await client.processExceptions(toItems(requests))

            expect(results).toHaveLength(5)
            for (let i = 0; i < inputs.length; i++) {
                if (inputs[i] === 'POISON') {
                    expect(results[i]).toMatchObject({ result: 'retry', error: { code: 'deadline_exceeded' } })
                } else {
                    expect(results[i]).toMatchObject({ value: { uuid: inputs[i] } })
                }
            }
        })
    })
})
