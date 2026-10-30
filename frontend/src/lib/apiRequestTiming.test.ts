import { ApiRequestTimingRecorder } from './apiRequestTiming'

const REQUEST_ID = '11111111-1111-4111-8111-111111111111'
const OTHER_REQUEST_ID = '22222222-2222-4222-8222-222222222222'

describe('API request timing', () => {
    const url = 'https://example.com/api/query/'
    let now: number
    let pending: PerformanceEntry[]
    let observer: ResourceObserver
    const originalObserver = Object.getOwnPropertyDescriptor(globalThis, 'PerformanceObserver')

    class ResourceObserver {
        observe = jest.fn()
        disconnect = jest.fn()
        takeRecords = jest.fn(() => pending.splice(0))

        constructor(private readonly callback: PerformanceObserverCallback) {
            observer = this
        }

        deliver(entries: PerformanceEntry[]): void {
            this.callback(
                { getEntries: () => entries } as PerformanceObserverEntryList,
                this as unknown as PerformanceObserver
            )
        }
    }

    const resource = (requestId = REQUEST_ID): PerformanceResourceTiming =>
        ({
            name: url,
            entryType: 'resource',
            startTime: 10,
            requestStart: 110,
            responseStart: 210,
            responseEnd: 310,
            serverTiming: [{ name: 'request_id', description: requestId, duration: 0 }],
        }) as unknown as PerformanceResourceTiming

    beforeEach(() => {
        now = 10
        pending = []
        Object.defineProperty(globalThis, 'PerformanceObserver', { configurable: true, value: ResourceObserver })
    })

    afterEach(() => {
        if (originalObserver) {
            Object.defineProperty(globalThis, 'PerformanceObserver', originalObserver)
        } else {
            delete (globalThis as { PerformanceObserver?: unknown }).PerformanceObserver
        }
    })

    describe('API request resource timing attribution', () => {
        let recorder: ApiRequestTimingRecorder

        beforeEach(() => {
            recorder = new ApiRequestTimingRecorder({ now: () => now })
            now = 210
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            now = 320
        })

        it('uses the exact response ID even when another request to the same URL overlaps', () => {
            pending = [resource(OTHER_REQUEST_ID), resource()]
            expect(recorder.finish()).toEqual(
                expect.objectContaining({
                    resource_timing_status: 'matched',
                    resource_pre_request_ms: 100,
                    resource_ttfb_ms: 100,
                    resource_download_ms: 100,
                    resource_callback_ms: 10,
                })
            )
        })

        it('does not associate an entry by URL or proximity when its ID differs', () => {
            pending = [resource(OTHER_REQUEST_ID)]
            expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'not_found' }))
            expect(recorder.finish()).not.toHaveProperty('resource_ttfb_ms')
        })

        it('rejects ambiguous matches instead of selecting the most recent request', () => {
            pending = [resource(), resource()]
            expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'ambiguous' }))
            expect(recorder.finish()).not.toHaveProperty('resource_pre_request_ms')
        })

        it.each([OTHER_REQUEST_ID, REQUEST_ID, 'invalid-id'])(
            'rejects a resource containing the response identity alongside %s',
            (secondIdentity) => {
                pending = [
                    {
                        ...resource(),
                        serverTiming: [
                            { name: 'request_id', description: REQUEST_ID, duration: 0 },
                            { name: 'request_id', description: secondIdentity, duration: 0 },
                        ],
                    } as unknown as PerformanceResourceTiming,
                ]
                const timing = recorder.finish()
                expect(timing.resource_timing_status).toBe('ambiguous')
                expect(timing.resource_ttfb_ms).toBeUndefined()
            }
        )

        it('leaves unavailable cross-origin phases unknown', () => {
            pending = [{ ...resource(), requestStart: 0, responseStart: 0 } as PerformanceResourceTiming]
            expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'restricted' }))
            expect(recorder.finish()).not.toHaveProperty('resource_ttfb_ms')
        })

        it.each([
            ['stale', { startTime: 1 }],
            ['out-of-order', { responseEnd: 400 }],
        ])('rejects %s timing entries', (_name, override) => {
            pending = [{ ...resource(), ...override } as PerformanceResourceTiming]
            expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'invalid' }))
        })

        it('does not use malformed request IDs or upstream durations', () => {
            recorder.recordHeaders({
                status: 200,
                url,
                headers: new Headers({ 'X-Request-ID': 'not-a-uuid', 'X-Envoy-Upstream-Service-Time': '-10' }),
            })
            pending = [resource()]
            expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'missing_request_id' }))
            expect(recorder.finish()).not.toHaveProperty('http_request_id')
            expect(recorder.finish()).not.toHaveProperty('envoy_upstream_ms')
        })

        it('retains application timings when resource timing is unavailable', () => {
            Object.defineProperty(globalThis, 'PerformanceObserver', {
                configurable: true,
                value: class {
                    constructor() {
                        throw new Error('Unavailable')
                    }
                },
            })
            recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            expect(recorder.finish()).toEqual(
                expect.objectContaining({
                    resource_timing_status: 'unavailable',
                    http_request_id: REQUEST_ID,
                })
            )
        })

        it.each(['abort', 'network'])('does not attribute an auth retry %s to the preceding response', (failure) => {
            pending = [resource()]
            recorder.startFetch(url)
            if (failure === 'network') {
                recorder.recordFailure({})
            }
            const timing = recorder.finish()
            expect(timing.resource_timing_status).toBe('missing_request_id')
            expect(timing.http_request_id).toBeUndefined()
            expect(timing.http_status).toBeUndefined()
            expect(timing.time_to_headers_ms).toBeUndefined()
            expect(timing.resource_ttfb_ms).toBeUndefined()
        })

        it('rejects the preceding auth response when a successful retry reuses its request ID', () => {
            pending = [resource()]
            recorder.startFetch(url)
            now = 500
            recorder.startFetch(url)
            now = 600
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            now = 700
            const timing = recorder.finish()
            expect(timing.request_total_ms).toBe(690)
            expect(timing.time_to_headers_ms).toBe(590)
            expect(timing.resource_timing_status).toBe('invalid')
            expect(timing.resource_ttfb_ms).toBeUndefined()
            expect(timing.fetch_attempts).toBe(2)
        })
    })

    describe('resource observation during an active request', () => {
        it('attributes a completed request even when the global resource buffer has stopped recording', () => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.startFetch(url)
            now = 210
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            // Resource callbacks may still be pending when the fetch body has completed.
            pending = [resource()]
            now = 320
            expect(recorder.finish()).toEqual(
                expect.objectContaining({ resource_timing_status: 'matched', resource_download_ms: 100 })
            )
            expect(observer.disconnect).toHaveBeenCalledTimes(1)
        })

        it('retains the matching identity when unrelated resources complete during the request', () => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            observer.deliver([resource(), ...Array.from({ length: 1000 }, () => resource(OTHER_REQUEST_ID))])
            now = 320
            expect(recorder.finish().resource_timing_status).toBe('matched')
        })

        it.each([
            ['unidentifiable resources', 40, (): PerformanceResourceTiming => ({ ...resource(), serverTiming: [] })],
            [
                'identified requests to other URLs',
                33,
                (): PerformanceResourceTiming => ({
                    ...resource(OTHER_REQUEST_ID),
                    name: 'https://example.com/api/environments/1/query/other/',
                }),
            ],
        ])('retains resource phases when %s complete before response headers', (_name, count, unrelated) => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.startFetch(url)
            observer.deliver([...Array.from({ length: count }, unrelated), resource()])
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            now = 320
            expect(recorder.finish()).toEqual(
                expect.objectContaining({ resource_timing_status: 'matched', resource_ttfb_ms: 100 })
            )
        })

        it('rejects duplicate identities observed within the request', () => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            observer.deliver([resource(), resource()])
            now = 320
            expect(recorder.finish().resource_timing_status).toBe('ambiguous')
        })

        it('leaves ownership unknown when bounded collection could have discarded a duplicate identity', () => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.startFetch(url)
            observer.deliver([resource(), ...Array.from({ length: 64 }, () => resource(OTHER_REQUEST_ID)), resource()])
            recorder.recordHeaders({ status: 200, url, headers: new Headers({ 'X-Request-ID': REQUEST_ID }) })
            now = 320
            const timing = recorder.finish()
            expect(timing.resource_timing_status).toBe('overflow')
            expect(timing.resource_ttfb_ms).toBeUndefined()
            expect(observer.disconnect).toHaveBeenCalledTimes(1)
        })

        it('disconnects after a request fails before receiving an identity', () => {
            const recorder = new ApiRequestTimingRecorder({ now: () => now })
            recorder.startFetch(url)
            recorder.recordFailure({})
            expect(recorder.finish().resource_timing_status).toBe('missing_request_id')
            expect(observer.disconnect).toHaveBeenCalledTimes(1)
        })
    })
})
