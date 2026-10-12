export interface ApiRequestTiming {
    request_total_ms: number
    // This includes API wrapper work and authentication retries before a successful response.
    time_to_headers_ms?: number
    body_read_ms?: number
    json_parse_ms?: number
    http_status?: number
    http_request_id?: string
    envoy_upstream_ms?: number
    resource_timing_status:
        | 'matched'
        | 'missing_request_id'
        | 'not_found'
        | 'ambiguous'
        | 'unavailable'
        | 'restricted'
        | 'invalid'
    // Pre-request includes connection setup and browser waiting; it is not a queue measurement.
    resource_pre_request_ms?: number
    resource_ttfb_ms?: number
    resource_download_ms?: number
    // Includes browser scheduling, body decoding, and parsing after network completion.
    resource_callback_ms?: number
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** One POST attempt, with resource phases attributed only by a server-provided request ID. */
export class ApiRequestTimingRecorder {
    private readonly startedAt: number
    private timing: Omit<ApiRequestTiming, 'request_total_ms' | 'resource_timing_status'> = {}
    private responseUrl?: string

    constructor(private readonly clock: Pick<Performance, 'now' | 'getEntriesByName'> = performance) {
        this.startedAt = clock.now()
    }

    startFetch(): void {
        // Authentication can retry internally; only the terminal fetch may supply response identity.
        this.timing = {}
        this.responseUrl = undefined
    }

    recordHeaders(response: { status?: number; headers?: Headers; url?: string }): void {
        this.timing.time_to_headers_ms = this.clock.now() - this.startedAt
        this.recordResponseMetadata(response)
    }

    recordFailure(error: { status?: number; headers?: Headers }): void {
        if (this.timing.http_status === undefined) {
            this.recordResponseMetadata(error)
        }
    }

    private recordResponseMetadata(response: { status?: number; headers?: Headers; url?: string }): void {
        this.timing.http_status = response.status
        const requestId = response.headers?.get('X-Request-ID')
        if (requestId && UUID_PATTERN.test(requestId)) {
            this.timing.http_request_id = requestId.toLowerCase()
        } else {
            delete this.timing.http_request_id
        }
        const upstream = response.headers?.get('X-Envoy-Upstream-Service-Time')
        if (upstream && /^\d+(\.\d+)?$/.test(upstream) && Number.isFinite(Number(upstream))) {
            this.timing.envoy_upstream_ms = Number(upstream)
        } else {
            delete this.timing.envoy_upstream_ms
        }
        this.responseUrl = response.url
    }

    async readBody(response: Response): Promise<string> {
        const startedAt = this.clock.now()
        try {
            return await response.text()
        } finally {
            this.timing.body_read_ms = this.clock.now() - startedAt
        }
    }

    parseJSON(text: string): unknown {
        const startedAt = this.clock.now()
        try {
            return JSON.parse(text)
        } finally {
            this.timing.json_parse_ms = this.clock.now() - startedAt
        }
    }

    finish(): ApiRequestTiming {
        const finishedAt = this.clock.now()
        const timing: ApiRequestTiming = {
            ...this.timing,
            request_total_ms: finishedAt - this.startedAt,
            resource_timing_status: 'missing_request_id',
        }
        if (!timing.http_request_id) {
            return timing
        }
        try {
            const entries = this.responseUrl ? this.clock.getEntriesByName(this.responseUrl, 'resource') : []
            const matches = (entries as PerformanceResourceTiming[]).filter((entry) =>
                entry.serverTiming?.some(
                    (serverTiming) =>
                        serverTiming.name === 'request_id' && serverTiming.description === timing.http_request_id
                )
            )
            timing.resource_timing_status = matches.length > 1 ? 'ambiguous' : 'not_found'
            if (matches.length !== 1) {
                return timing
            }
            const entry = matches[0]
            if (entry.requestStart === 0 || entry.responseStart === 0) {
                timing.resource_timing_status = 'restricted'
                return timing
            }
            const phases = [entry.startTime, entry.requestStart, entry.responseStart, entry.responseEnd, finishedAt]
            if (
                entry.startTime < this.startedAt - 1 ||
                phases.some((phase, index) => !Number.isFinite(phase) || (index > 0 && phase < phases[index - 1]))
            ) {
                timing.resource_timing_status = 'invalid'
                return timing
            }
            timing.resource_timing_status = 'matched'
            timing.resource_pre_request_ms = entry.requestStart - entry.startTime
            timing.resource_ttfb_ms = entry.responseStart - entry.requestStart
            timing.resource_download_ms = entry.responseEnd - entry.responseStart
            timing.resource_callback_ms = finishedAt - entry.responseEnd
        } catch {
            timing.resource_timing_status = 'unavailable'
        }
        return timing
    }
}
