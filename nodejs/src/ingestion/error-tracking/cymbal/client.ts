import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import { logger } from '~/utils/logger'
import { FetchResponse, internalFetch } from '~/utils/request'

import { CymbalRequest, CymbalResponse } from './types'

// ────────────────────────────────────────────────────────────────────
// Public types
// ────────────────────────────────────────────────────────────────────

/** Result for a single event from Cymbal processing. */
export type CymbalEventResult =
    | { status: 'success'; response: CymbalResponse | null }
    | { status: 'failed'; retriable: boolean; reason: string }

/** Function signature for fetch implementation */
export type FetchFunction = (
    url: string,
    options: { method: string; headers: Record<string, string>; body: string; timeoutMs: number }
) => Promise<FetchResponse>

export interface CymbalClientConfig {
    baseUrl: string
    timeoutMs: number
    /** Target max body size in bytes for proactive chunking. */
    maxBodyBytes: number
    /** Custom fetch implementation for testing. Defaults to internalFetch. */
    fetch?: FetchFunction
}

// ────────────────────────────────────────────────────────────────────
// Error model — two booleans drive caller behavior, set at throw site
// so catchers don't need to re-categorize.
// ────────────────────────────────────────────────────────────────────

/**
 * Error class for failures from Cymbal.
 *
 * - `isRetriable` — whether the wrapper should attempt this event again
 *   (5xx, 429, timeout, network: true; 4xx, parse errors: false).
 * - `canFanOut` — whether the failure is plausibly single-event-triggered,
 *   so per-event probing could isolate the offender. True for timeouts
 *   and 500; false for 429 (explicit backpressure — fanning out would
 *   amplify load), infrastructure 5xx (hit everything equally), 4xx
 *   (per-event probing won't change the verdict), and non-timeout
 *   network errors.
 */
class CymbalError extends Error {
    isRetriable: boolean
    canFanOut: boolean

    constructor(message: string, isRetriable: boolean, canFanOut: boolean) {
        super(message)
        this.name = 'CymbalError'
        this.isRetriable = isRetriable
        this.canFanOut = canFanOut
    }
}

/**
 * Translate any thrown error into the wrapper's per-event failure fields.
 * Cymbal errors carry their own retriable verdict; anything else is treated
 * as retriable since it's an unexpected failure (network, JSON parsing in
 * fetch internals, etc.) where a retry is the safe default.
 */
function classifyClientError(error: unknown): { retriable: boolean; reason: string } {
    if (error instanceof CymbalError) {
        return { retriable: error.isRetriable, reason: error.message }
    }
    return { retriable: true, reason: error instanceof Error ? error.message : String(error) }
}

// ────────────────────────────────────────────────────────────────────
// Response validation
// ────────────────────────────────────────────────────────────────────

const CymbalResponseSchema = z.object({
    uuid: z.string(),
    event: z.string(),
    team_id: z.number(),
    timestamp: z.string(),
    properties: z.record(z.string(), z.unknown()),
})

const CymbalResponseArraySchema = z.array(CymbalResponseSchema.nullable())

// ────────────────────────────────────────────────────────────────────
// Metrics
// ────────────────────────────────────────────────────────────────────

const cymbalRequestDuration = new Histogram({
    name: 'error_tracking_cymbal_request_duration_ms',
    help: 'Duration of Cymbal API requests in milliseconds',
    labelNames: ['status'],
    buckets: [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000],
})

const cymbalRequestCounter = new Counter({
    name: 'error_tracking_cymbal_requests_total',
    help: 'Total Cymbal API requests',
    labelNames: ['status'],
})

const cymbalBatchSizeHistogram = new Histogram({
    name: 'error_tracking_cymbal_batch_size',
    help: 'Size of batches sent to Cymbal API',
    buckets: [1, 5, 10, 25, 50, 100, 250, 500],
})

const cymbalChunksPerBatchHistogram = new Histogram({
    name: 'error_tracking_cymbal_chunks_per_batch',
    help: 'Number of HTTP requests per batch (1 = no chunking needed)',
    buckets: [1, 2, 3, 4, 5, 10],
})

const cymbalFanOutEventsCounter = new Counter({
    name: 'error_tracking_cymbal_fan_out_events_total',
    help: 'Events probed individually via fan-out (load amplification signal)',
})

function recordRequestMetrics(status: string, durationMs: number, batchSize: number): void {
    cymbalRequestDuration.labels({ status }).observe(durationMs)
    cymbalRequestCounter.labels({ status }).inc()
    logger.debug('📊', 'cymbal_batch_request_complete', {
        status,
        durationMs: Math.round(durationMs),
        batchSize,
    })
}

// ────────────────────────────────────────────────────────────────────
// Client
// ────────────────────────────────────────────────────────────────────

/**
 * HTTP client for communicating with the Cymbal symbolication service.
 *
 * Cymbal is responsible for:
 * - Stack trace symbolication (source maps, debug symbols)
 * - Issue fingerprinting and grouping
 * - Issue suppression based on status
 *
 * Note: This client does not implement retry logic. Retries are handled at
 * the pipeline level using pipeBatchWithRetry(). The client returns per-event
 * failed results with a retriable flag for the wrapper to handle.
 */
export class CymbalClient {
    private baseUrl: string
    private timeoutMs: number
    private maxBodyBytes: number
    private fetch: FetchFunction
    /** Per-event fan-out concurrency on a recoverable chunk failure. */
    private static readonly FAN_OUT_CONCURRENCY = 10

    constructor(config: CymbalClientConfig) {
        this.baseUrl = config.baseUrl
        this.timeoutMs = config.timeoutMs
        this.maxBodyBytes = config.maxBodyBytes
        this.fetch = config.fetch ?? internalFetch
    }

    /**
     * Process a batch of exception events through Cymbal.
     *
     * Chunks the input by estimated body size so no single request blows
     * past Cymbal's body limit. Chunk failures that are plausibly
     * single-event-triggered (timeouts, 500) fan out to per-event calls
     * to isolate the offender — other failures (429 backpressure,
     * infrastructure 5xx, 4xx, parse errors) broadcast the chunk-level
     * verdict to the chunk's events without per-event probing. Either
     * way, each event in a failed chunk gets a verdict and remaining
     * chunks still run — failure in one chunk never discards another
     * chunk's results, so the wrapper can target its retries precisely.
     *
     * Fan-out load amplification is observable via the
     * `error_tracking_cymbal_fan_out_events_total` counter. A separate
     * circuit breaker (forthcoming) will pace consumption when the
     * dependency is degraded service-wide.
     *
     * @param items - Array of requests paired with their estimated byte size
     * @returns Array of results maintaining 1:1 position correspondence with input.
     *          Each result is either a success (with response or null for suppressed)
     *          or a failure with retriable flag for the pipeline wrapper to handle.
     */
    async processExceptions(items: { request: CymbalRequest; estimatedSize: number }[]): Promise<CymbalEventResult[]> {
        if (items.length === 0) {
            return []
        }
        cymbalBatchSizeHistogram.observe(items.length)

        const chunks = this.chunkByEstimatedSize(items)
        cymbalChunksPerBatchHistogram.observe(chunks.length)
        const allResults: CymbalEventResult[] = []

        for (const chunk of chunks) {
            try {
                const responses = await this.processChunk(chunk.map((item) => item.request))
                allResults.push(...responses.map((response) => ({ status: 'success' as const, response })))
            } catch (error) {
                if (error instanceof CymbalError && error.canFanOut && chunk.length > 1) {
                    logger.warn('⚠️', 'cymbal_fan_out', { chunkSize: chunk.length, reason: error.message })
                    cymbalFanOutEventsCounter.inc(chunk.length)
                    allResults.push(...(await this.fanOut(chunk)))
                } else {
                    const failure = { status: 'failed' as const, ...classifyClientError(error) }
                    allResults.push(...chunk.map(() => failure))
                }
            }
        }

        return allResults
    }

    /**
     * Fan out a failed chunk to per-event calls. Each event gets a single
     * attempt and gets its own verdict. The per-promise catch ensures a
     * failure in one call doesn't discard the successful peers' results
     * (the whole point of fanning out is per-event resolution).
     */
    private async fanOut(items: { request: CymbalRequest; estimatedSize: number }[]): Promise<CymbalEventResult[]> {
        const results: CymbalEventResult[] = []
        for (let i = 0; i < items.length; i += CymbalClient.FAN_OUT_CONCURRENCY) {
            const batch = items.slice(i, i + CymbalClient.FAN_OUT_CONCURRENCY)
            const batchResults = await Promise.all(
                batch.map(async ({ request }): Promise<CymbalEventResult> => {
                    try {
                        const [response] = await this.processChunk([request])
                        return { status: 'success', response }
                    } catch (error) {
                        return { status: 'failed', ...classifyClientError(error) }
                    }
                })
            )
            results.push(...batchResults)
        }
        return results
    }

    /** Process a single chunk of requests through Cymbal's HTTP API. */
    private async processChunk(requests: CymbalRequest[]): Promise<(CymbalResponse | null)[]> {
        const { response, durationMs } = await this.makeRequest(requests)

        if (response.status >= 400) {
            recordRequestMetrics(`error_${response.status}`, durationMs, requests.length)
            logger.warn('⚠️', 'cymbal_error_response', { status: response.status, batchSize: requests.length })
            // 5xx and 429 are retriable. Only 500 is worth fanning out for —
            // it maps to Cymbal's unhandled-error path, which can be triggered
            // by one event's data. Other 5xx (502/503/504) come from
            // infrastructure (envoy, load balancer) and hit every event the
            // same; 429 is explicit backpressure and fanning out would
            // amplify load.
            const isRetriable = response.status >= 500 || response.status === 429
            const canFanOut = response.status === 500
            throw new CymbalError(`Cymbal returned ${response.status}`, isRetriable, canFanOut)
        }

        const rawResults = await response.json()
        const parseResult = CymbalResponseArraySchema.safeParse(rawResults)
        if (!parseResult.success) {
            recordRequestMetrics('error_invalid_response', durationMs, requests.length)
            throw new CymbalError(`Invalid Cymbal response: ${parseResult.error.message}`, false, false)
        }

        if (parseResult.data.length !== requests.length) {
            recordRequestMetrics('error_length_mismatch', durationMs, requests.length)
            throw new CymbalError(
                `Cymbal response length mismatch: got ${parseResult.data.length}, expected ${requests.length}`,
                false,
                false
            )
        }

        recordRequestMetrics('success', durationMs, requests.length)
        return parseResult.data
    }

    /** Make HTTP request to Cymbal, wrapping network errors as retriable CymbalErrors. */
    private async makeRequest(requests: CymbalRequest[]): Promise<{ response: FetchResponse; durationMs: number }> {
        const startTime = performance.now()
        try {
            const response = await this.fetch(`${this.baseUrl}/process`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requests),
                timeoutMs: this.timeoutMs,
            })
            return { response, durationMs: performance.now() - startTime }
        } catch (error) {
            const durationMs = performance.now() - startTime
            recordRequestMetrics('error', durationMs, requests.length)
            // Network/timeout errors are retriable. Only timeouts are worth
            // fanning out for — a slow event might be the cause and per-event
            // calls can isolate it. Non-timeout network errors hit every
            // request equally; probing won't help.
            const isTimeout = error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')
            throw new CymbalError(error instanceof Error ? error.message : String(error), true, isTimeout)
        }
    }

    /**
     * Split items into chunks using estimated byte sizes. Greedily fills
     * each chunk until adding the next item would exceed maxBodyBytes.
     * A single item that exceeds the limit gets its own chunk.
     */
    private chunkByEstimatedSize(
        items: { request: CymbalRequest; estimatedSize: number }[]
    ): { request: CymbalRequest; estimatedSize: number }[][] {
        const chunks: { request: CymbalRequest; estimatedSize: number }[][] = []
        let currentChunk: { request: CymbalRequest; estimatedSize: number }[] = []
        let currentSize = 0

        for (const item of items) {
            if (currentChunk.length > 0 && currentSize + item.estimatedSize > this.maxBodyBytes) {
                chunks.push(currentChunk)
                currentChunk = [item]
                currentSize = item.estimatedSize
            } else {
                currentChunk.push(item)
                currentSize += item.estimatedSize
            }
        }

        if (currentChunk.length > 0) {
            chunks.push(currentChunk)
        }

        return chunks
    }
}
