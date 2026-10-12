import { ApiRequestTimingRecorder } from './apiRequestTiming'

const REQUEST_ID = '11111111-1111-4111-8111-111111111111'
const OTHER_REQUEST_ID = '22222222-2222-4222-8222-222222222222'

describe('API request resource timing attribution', () => {
    let now: number
    let entries: PerformanceResourceTiming[]
    let recorder: ApiRequestTimingRecorder

    const resource = (requestId = REQUEST_ID): PerformanceResourceTiming =>
        ({
            startTime: 10,
            requestStart: 110,
            responseStart: 210,
            responseEnd: 310,
            serverTiming: [{ name: 'request_id', description: requestId }],
        }) as unknown as PerformanceResourceTiming

    beforeEach(() => {
        now = 10
        entries = []
        recorder = new ApiRequestTimingRecorder({ now: () => now, getEntriesByName: () => entries })
        now = 210
        recorder.recordHeaders({
            status: 200,
            url: 'https://example.com/api/query/',
            headers: new Headers({ 'X-Request-ID': REQUEST_ID }),
        })
        now = 320
    })

    it('uses the exact response ID even when another request to the same URL overlaps', () => {
        entries = [resource(OTHER_REQUEST_ID), resource()]
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
        entries = [resource(OTHER_REQUEST_ID)]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'not_found' }))
        expect(recorder.finish()).not.toHaveProperty('resource_ttfb_ms')
    })

    it('rejects ambiguous matches instead of selecting the most recent request', () => {
        entries = [resource(), resource()]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'ambiguous' }))
        expect(recorder.finish()).not.toHaveProperty('resource_pre_request_ms')
    })

    it('leaves unavailable cross-origin phases unknown', () => {
        entries = [{ ...resource(), requestStart: 0, responseStart: 0 } as PerformanceResourceTiming]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'restricted' }))
        expect(recorder.finish()).not.toHaveProperty('resource_ttfb_ms')
    })

    it('rejects stale or out-of-order timing entries', () => {
        entries = [{ ...resource(), startTime: 1 } as PerformanceResourceTiming]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'invalid' }))
        entries = [{ ...resource(), responseEnd: 400 } as PerformanceResourceTiming]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'invalid' }))
    })

    it('does not use malformed request IDs or upstream durations', () => {
        recorder.recordHeaders({
            status: 200,
            url: 'https://example.com/api/query/',
            headers: new Headers({ 'X-Request-ID': 'not-a-uuid', 'X-Envoy-Upstream-Service-Time': '-10' }),
        })
        entries = [resource()]
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'missing_request_id' }))
        expect(recorder.finish()).not.toHaveProperty('http_request_id')
        expect(recorder.finish()).not.toHaveProperty('envoy_upstream_ms')
    })

    it('retains application timings when resource timing is unavailable', () => {
        recorder = new ApiRequestTimingRecorder({
            now: () => now,
            getEntriesByName: () => {
                throw new Error('Unavailable')
            },
        })
        recorder.recordHeaders({
            status: 200,
            url: 'https://example.com/api/query/',
            headers: new Headers({ 'X-Request-ID': REQUEST_ID }),
        })
        expect(recorder.finish()).toEqual(expect.objectContaining({ resource_timing_status: 'unavailable' }))
    })

    it.each(['abort', 'network'])('does not attribute an auth retry %s to the preceding response', (failure) => {
        entries = [resource()]
        recorder.startFetch()
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
})
