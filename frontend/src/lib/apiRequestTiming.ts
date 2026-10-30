import { isUUIDLike } from 'lib/utils/guards'

export interface ApiRequestTiming {
    request_total_ms: number
    // This includes API wrapper work and authentication retries before a successful response.
    time_to_headers_ms?: number
    body_read_ms?: number
    json_parse_ms?: number
    http_status?: number
    // Above 1 when authentication refreshed and retried the request.
    fetch_attempts?: number
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
        | 'overflow'
    // Pre-request includes connection setup and browser waiting; it is not a queue measurement.
    resource_pre_request_ms?: number
    resource_ttfb_ms?: number
    resource_download_ms?: number
    // Includes browser scheduling, body decoding, and parsing after network completion.
    resource_callback_ms?: number
}

const FLATTENED_REQUEST_TIMING_FIELDS = [
    'http_request_id',
    'time_to_headers_ms',
    'body_read_ms',
    'json_parse_ms',
    'resource_timing_status',
    'envoy_upstream_ms',
    'resource_pre_request_ms',
    'resource_ttfb_ms',
    'request_total_ms',
    'http_status',
] as const

export function flattenRequestTiming(
    timing: ApiRequestTiming | undefined,
    prefix: '' | 'result_poll_'
): Record<string, string | number | undefined> {
    if (!timing) {
        return {}
    }
    return Object.fromEntries(FLATTENED_REQUEST_TIMING_FIELDS.map((field) => [`${prefix}${field}`, timing[field]]))
}

const MAX_PENDING_RESOURCES = 32

type ResourceTiming = Pick<
    ApiRequestTiming,
    | 'resource_timing_status'
    | 'resource_pre_request_ms'
    | 'resource_ttfb_ms'
    | 'resource_download_ms'
    | 'resource_callback_ms'
>

function serverRequestIds(entry: PerformanceResourceTiming): string[] {
    return (entry.serverTiming ?? [])
        .filter((metric) => metric.name === 'request_id')
        .map((metric) => metric.description.toLowerCase())
}

/** One API request, with resource phases attributed only by a server-provided request ID. */
export class ApiRequestTimingRecorder {
    private readonly startedAt: number
    private fetchStartedAt: number
    private requestUrl?: string
    private timing: Omit<ApiRequestTiming, 'request_total_ms' | 'resource_timing_status'> = {}
    private responseUrl?: string
    private observer?: PerformanceObserver
    private resourceEntries: PerformanceResourceTiming[] = []
    private resourceCollectionOverflowed = false
    private fetchAttempts = 0

    constructor(private readonly clock: Pick<Performance, 'now'> = performance) {
        this.startedAt = clock.now()
        this.fetchStartedAt = this.startedAt
        try {
            this.observer = new PerformanceObserver((list) => this.collectResources(list.getEntries()))
            // Observe only new entries: the global buffer can fill during a long-lived app session.
            this.observer.observe({ type: 'resource' })
        } catch {
            this.observer?.disconnect()
            this.observer = undefined
        }
    }

    startFetch(url: string): void {
        // Authentication can retry internally; only the terminal fetch may supply response identity.
        this.timing = {}
        this.responseUrl = undefined
        this.resourceEntries = []
        this.resourceCollectionOverflowed = false
        this.fetchStartedAt = this.clock.now()
        this.fetchAttempts++
        try {
            this.requestUrl = new URL(url, location.href).href
        } catch {
            this.requestUrl = undefined
        }
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
        if (requestId && isUUIDLike(requestId)) {
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
        if (this.timing.http_request_id && this.responseUrl) {
            this.resourceEntries = this.resourceEntries.filter((entry) => this.isResponseEntry(entry)).slice(0, 2)
        }
    }

    private isResponseEntry(entry: PerformanceResourceTiming): boolean {
        return (
            entry.name === this.responseUrl &&
            serverRequestIds(entry).some((requestId) => requestId === this.timing.http_request_id)
        )
    }

    private collectResources(entries: PerformanceEntry[]): void {
        for (const entry of entries as PerformanceResourceTiming[]) {
            if (entry.entryType !== 'resource') {
                continue
            }
            if (this.timing.http_request_id && this.responseUrl) {
                // Two candidates already prove ambiguity; unrelated resources need no retention.
                if (this.resourceEntries.length < 2 && this.isResponseEntry(entry)) {
                    this.resourceEntries.push(entry)
                }
            } else if (this.isPendingRequestEntry(entry)) {
                if (this.resourceEntries.length === MAX_PENDING_RESOURCES) {
                    this.resourceCollectionOverflowed = true
                    this.resourceEntries.shift()
                }
                this.resourceEntries.push(entry)
            }
        }
    }

    private isPendingRequestEntry(entry: PerformanceResourceTiming): boolean {
        if (entry.name !== this.requestUrl || entry.startTime < this.fetchStartedAt - 1) {
            return false
        }
        return serverRequestIds(entry).some(isUUIDLike)
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
            ...(this.fetchAttempts ? { fetch_attempts: this.fetchAttempts } : {}),
            resource_timing_status: 'missing_request_id',
        }
        try {
            // Fetch/body promises can resolve before the observer callback is delivered.
            this.collectResources(this.observer?.takeRecords() ?? [])
            if (timing.http_request_id) {
                Object.assign(timing, this.resourceTiming(timing.http_request_id, finishedAt))
            }
        } catch {
            timing.resource_timing_status = 'unavailable'
        } finally {
            this.observer?.disconnect()
        }
        return timing
    }

    private resourceTiming(requestId: string, finishedAt: number): ResourceTiming {
        if (!this.observer) {
            return { resource_timing_status: 'unavailable' }
        }
        if (this.resourceCollectionOverflowed) {
            // Truncation may have hidden a duplicate identity; retained entries cannot prove ownership.
            return { resource_timing_status: 'overflow' }
        }
        const matches = this.resourceEntries.filter((entry) => serverRequestIds(entry).includes(requestId))
        if (matches.length !== 1) {
            return { resource_timing_status: matches.length > 1 ? 'ambiguous' : 'not_found' }
        }
        const entry = matches[0]
        const status = this.matchedEntryStatus(entry, finishedAt)
        if (status !== 'matched') {
            return { resource_timing_status: status }
        }
        return {
            resource_timing_status: 'matched',
            resource_pre_request_ms: entry.requestStart - entry.startTime,
            resource_ttfb_ms: entry.responseStart - entry.requestStart,
            resource_download_ms: entry.responseEnd - entry.responseStart,
            resource_callback_ms: finishedAt - entry.responseEnd,
        }
    }

    private matchedEntryStatus(
        entry: PerformanceResourceTiming,
        finishedAt: number
    ): ApiRequestTiming['resource_timing_status'] {
        const identities = serverRequestIds(entry)
        if (identities.length !== 1 || !isUUIDLike(identities[0])) {
            return 'ambiguous'
        }
        if (entry.requestStart === 0 || entry.responseStart === 0) {
            return 'restricted'
        }
        const phases = [entry.startTime, entry.requestStart, entry.responseStart, entry.responseEnd, finishedAt]
        if (
            entry.startTime < this.fetchStartedAt - 1 ||
            phases.some((phase, index) => !Number.isFinite(phase) || (index > 0 && phase < phases[index - 1]))
        ) {
            return 'invalid'
        }
        return 'matched'
    }
}
