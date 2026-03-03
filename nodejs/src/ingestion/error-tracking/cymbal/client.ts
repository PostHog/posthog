import { Counter, Histogram } from 'prom-client'

import { logger } from '~/utils/logger'
import { FetchResponse, internalFetch } from '~/utils/request'
import { retryIfRetriable } from '~/utils/retries'

import { CymbalRequest, CymbalResponse } from './types'

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

const cymbalRetryCounter = new Counter({
    name: 'error_tracking_cymbal_retries_total',
    help: 'Total Cymbal API request retries',
    labelNames: ['reason'],
})

/** Function signature for fetch implementation */
export type FetchFunction = (
    url: string,
    options: { method: string; headers: Record<string, string>; body: string; timeoutMs: number }
) => Promise<FetchResponse>

export interface CymbalClientConfig {
    baseUrl: string
    timeoutMs: number
    /** Maximum number of attempts (including the initial request). Defaults to 3. */
    maxAttempts?: number
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
 */
export class CymbalClient {
    private baseUrl: string
    private timeoutMs: number
    private maxAttempts: number
    private fetch: FetchFunction

    constructor(config: CymbalClientConfig) {
        this.baseUrl = config.baseUrl.replace(/\/$/, '') // Remove trailing slash
        this.timeoutMs = config.timeoutMs
        this.maxAttempts = config.maxAttempts ?? 3
        this.fetch = config.fetch ?? internalFetch
    }

    /**
     * Process a batch of exception events through Cymbal.
     *
     * @param requests - Array of exception events to process
     * @returns Array of processed events with symbolicated stack traces and fingerprints.
     *          Null entries indicate events that should be dropped (e.g., suppressed issues).
     *          Maintains 1:1 position correspondence with input array.
     */
    async processExceptions(requests: CymbalRequest[]): Promise<(CymbalResponse | null)[]> {
        if (requests.length === 0) {
            return []
        }

        cymbalBatchSizeHistogram.observe(requests.length)

        return retryIfRetriable(
            () => this.doProcessExceptions(requests),
            this.maxAttempts,
            100 // Start with 100ms backoff
        )
    }

    private async doProcessExceptions(requests: CymbalRequest[]): Promise<(CymbalResponse | null)[]> {
        const startTime = performance.now()
        let status = 'success'

        try {
            const response = await this.fetch(`${this.baseUrl}/process`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requests),
                timeoutMs: this.timeoutMs,
            })

            if (response.status >= 400) {
                status = `error_${response.status}`
                const errorBody = await response.text().catch(() => 'unknown')

                // Log the error for debugging - Cymbal returns {error, details} format
                logger.warn('⚠️', 'cymbal_error_response', {
                    status: response.status,
                    errorBody,
                    batchSize: requests.length,
                })

                // 5xx errors and 429 are retriable
                const isRetriable = response.status >= 500 || response.status === 429
                if (isRetriable) {
                    cymbalRetryCounter.inc({ reason: response.status === 429 ? 'rate_limit' : 'server_error' })
                }

                throw new CymbalError(`Cymbal returned ${response.status}: ${errorBody}`, isRetriable)
            }

            const results: (CymbalResponse | null)[] = await response.json()

            // Validate response array length matches request
            if (results.length !== requests.length) {
                throw new CymbalError(
                    `Cymbal response length mismatch: got ${results.length}, expected ${requests.length}`,
                    false // Not retriable - indicates a bug
                )
            }

            // Return results as-is. Cymbal returns null for suppressed events.
            return results
        } catch (error) {
            if (error instanceof CymbalError) {
                throw error
            }

            // All other errors (timeout, network) are retriable infrastructure issues
            const isTimeout = error instanceof Error && error.name === 'TimeoutError'
            status = 'error'
            cymbalRetryCounter.inc({ reason: isTimeout ? 'timeout' : 'network_error' })
            throw new CymbalError(error instanceof Error ? error.message : String(error), true)
        } finally {
            const durationMs = performance.now() - startTime
            cymbalRequestDuration.labels({ status }).observe(durationMs)
            cymbalRequestCounter.labels({ status }).inc()

            logger.debug('📊', 'cymbal_batch_request_complete', {
                status,
                durationMs: Math.round(durationMs),
                batchSize: requests.length,
            })
        }
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
