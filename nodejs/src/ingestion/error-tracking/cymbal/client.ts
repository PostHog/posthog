import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import { logger } from '~/utils/logger'
import { FetchResponse, internalFetch } from '~/utils/request'

import { CymbalRequest, CymbalResponse } from './types'

/** Zod schema for validating Cymbal API responses */
const CymbalResponseSchema = z.object({
    uuid: z.string(),
    event: z.string(),
    team_id: z.number(),
    timestamp: z.string(),
    properties: z.record(z.unknown()),
})

const CymbalResponseArraySchema = z.array(CymbalResponseSchema.nullable())

const cymbalRequestDuration = new Histogram({
    name: 'error_tracking_cymbal_request_duration_ms',
    help: 'Duration of Cymbal API requests in milliseconds',
    labelNames: ['status'],
    buckets: [10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
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

/**
 * Error class that indicates whether the error is retriable.
 */
class CymbalError extends Error {
    isRetriable: boolean

    constructor(message: string, isRetriable: boolean) {
        super(message)
        this.name = 'CymbalError'
        this.isRetriable = isRetriable
    }
}

/**
 * HTTP client for communicating with the Cymbal symbolication service.
 *
 * Cymbal is responsible for:
 * - Stack trace symbolication (source maps, debug symbols)
 * - Issue fingerprinting and grouping
 * - Issue suppression based on status
 *
 * Note: This client does not implement retry logic. Retries are handled at
 * the pipeline level using pipeBatchWithRetry(). The client throws CymbalError
 * with isRetriable flag to indicate whether errors should be retried.
 */
export class CymbalClient {
    private baseUrl: string
    private timeoutMs: number
    private maxBodyBytes: number
    private fetch: FetchFunction

    constructor(config: CymbalClientConfig) {
        this.baseUrl = config.baseUrl.replace(/\/$/, '') // Remove trailing slash
        this.timeoutMs = config.timeoutMs
        this.maxBodyBytes = config.maxBodyBytes
        this.fetch = config.fetch ?? internalFetch
    }

    /**
     * Process a batch of exception events through Cymbal.
     *
     * Uses estimated byte sizes (from the original Kafka messages) to proactively
     * split batches that would exceed Cymbal's body size limit. This avoids
     * wasted HTTP roundtrips from 413 rejections without requiring serialization
     * to measure size.
     *
     * @param items - Array of requests paired with their estimated byte size
     *        (e.g. from Kafka message.value.length).
     * @returns Array of processed events with symbolicated stack traces and fingerprints.
     *          Null entries indicate events that should be dropped (e.g., suppressed issues).
     *          Maintains 1:1 position correspondence with input array.
     * @throws CymbalError with isRetriable flag indicating whether the error should be retried
     */
    async processExceptions(
        items: { request: CymbalRequest; estimatedSize: number }[]
    ): Promise<(CymbalResponse | null)[]> {
        if (items.length === 0) {
            return []
        }

        cymbalBatchSizeHistogram.observe(items.length)

        const chunks = this.chunkByEstimatedSize(items)
        cymbalChunksPerBatchHistogram.observe(chunks.length)
        const allResults: (CymbalResponse | null)[] = []

        for (const chunk of chunks) {
            const results = await this.processChunk(chunk.map((item) => item.request))
            allResults.push(...results)
        }

        return allResults
    }

    /**
     * Process a single chunk of requests through Cymbal's HTTP API.
     */
    private async processChunk(requests: CymbalRequest[]): Promise<(CymbalResponse | null)[]> {
        const { response, durationMs } = await this.makeRequest(requests)

        if (response.status >= 400) {
            this.recordMetrics(`error_${response.status}`, durationMs, requests.length)

            logger.warn('⚠️', 'cymbal_error_response', {
                status: response.status,
                batchSize: requests.length,
            })

            // 5xx errors and 429 are retriable
            const isRetriable = response.status >= 500 || response.status === 429
            throw new CymbalError(`Cymbal returned ${response.status}`, isRetriable)
        }

        const rawResults = await response.json()

        // Validate response structure using Zod schema
        const parseResult = CymbalResponseArraySchema.safeParse(rawResults)
        if (!parseResult.success) {
            this.recordMetrics('error_invalid_response', durationMs, requests.length)
            throw new CymbalError(`Invalid Cymbal response: ${parseResult.error.message}`, false)
        }

        const results = parseResult.data

        // Validate response array length matches request
        if (results.length !== requests.length) {
            this.recordMetrics('error_length_mismatch', durationMs, requests.length)
            throw new CymbalError(
                `Cymbal response length mismatch: got ${results.length}, expected ${requests.length}`,
                false
            )
        }

        this.recordMetrics('success', durationMs, requests.length)
        return results as (CymbalResponse | null)[]
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

    /**
     * Make HTTP request to Cymbal, wrapping network errors as retriable CymbalErrors.
     */
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
            this.recordMetrics('error', durationMs, requests.length)
            // Network/timeout errors are retriable
            throw new CymbalError(error instanceof Error ? error.message : String(error), true)
        }
    }

    private recordMetrics(status: string, durationMs: number, batchSize: number): void {
        cymbalRequestDuration.labels({ status }).observe(durationMs)
        cymbalRequestCounter.labels({ status }).inc()
        logger.debug('📊', 'cymbal_batch_request_complete', {
            status,
            durationMs: Math.round(durationMs),
            batchSize,
        })
    }

    /**
     * Health check for Cymbal service.
     */
    async healthCheck(): Promise<boolean> {
        try {
            const response = await this.fetch(`${this.baseUrl}/_liveness`, {
                method: 'GET',
                headers: {},
                body: '',
                timeoutMs: 5000,
            })

            return response.status >= 200 && response.status < 300
        } catch {
            return false
        }
    }
}
