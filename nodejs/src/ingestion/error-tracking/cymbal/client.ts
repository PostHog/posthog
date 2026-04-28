import dns from 'dns/promises'
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
    properties: z.record(z.string(), z.unknown()),
})

const CymbalResponseArraySchema = z.array(CymbalResponseSchema.nullable())

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

const cymbalChunksPerGroupHistogram = new Histogram({
    name: 'error_tracking_cymbal_chunks_per_routing_group',
    help: 'Number of HTTP requests per routing group (1 = no chunking needed)',
    buckets: [1, 2, 3, 4, 5, 10],
})

const cymbalRoutingGroupsHistogram = new Histogram({
    name: 'error_tracking_cymbal_routing_groups',
    help: 'Number of distinct team routing groups per batch',
    buckets: [1, 2, 3, 5, 10, 20, 50],
})

/** Function signature for fetch implementation */
export type FetchFunction = (
    url: string,
    options: { method: string; headers: Record<string, string>; body: string; timeoutMs: number }
) => Promise<FetchResponse>

/** Function signature for DNS resolution, injectable for testing */
export type DnsResolveFunction = (hostname: string) => Promise<string[]>

export interface CymbalClientConfig {
    baseUrl: string
    timeoutMs: number
    /** Target max body size in bytes for proactive chunking. */
    maxBodyBytes: number
    /** Custom fetch implementation for testing. Defaults to internalFetch. */
    fetch?: FetchFunction
    /** Custom DNS resolution function for testing. */
    dnsResolve?: DnsResolveFunction
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
 * Jump consistent hash — maps a key to one of numBuckets slots with minimal
 * reassignment when the bucket count changes. Based on the algorithm from
 * Lamping & Veach (Google, 2014).
 *
 * Uses a linear congruential generator that stays within 31-bit integers
 * to avoid JavaScript floating-point precision loss.
 */
function jumpConsistentHash(key: number, numBuckets: number): number {
    let b = -1
    let j = 0
    let seed = key >>> 0
    while (j < numBuckets) {
        b = j
        seed = (Math.imul(seed, 1103515245) + 12345) & 0x7fffffff
        j = Math.floor(((b + 1) * 0x80000000) / (seed + 1))
    }
    return b
}

/**
 * HTTP client for communicating with the Cymbal symbolication service.
 *
 * Cymbal is responsible for:
 * - Stack trace symbolication (source maps, debug symbols)
 * - Issue fingerprinting and grouping
 * - Issue suppression based on status
 *
 * Before each batch, the client resolves the base URL hostname via DNS.
 * When the hostname points to a headless K8s Service, DNS returns all pod
 * IPs — the client then groups events by team_id and routes each group to
 * a consistent pod using jump consistent hashing. This improves cache
 * locality since events from the same team always hit the same pod,
 * keeping its source map cache warm.
 *
 * When DNS returns a single IP (e.g., local dev or ClusterIP service),
 * all events are sent to that address — no grouping overhead.
 *
 * Note: This client does not implement retry logic. Retries are handled at
 * the pipeline level using pipeBatchWithRetry(). The client throws CymbalError
 * with isRetriable flag to indicate whether errors should be retried.
 */
export class CymbalClient {
    private hostname: string
    private port: string
    private timeoutMs: number
    private maxBodyBytes: number
    private fetch: FetchFunction
    private dnsResolve: DnsResolveFunction

    constructor(config: CymbalClientConfig) {
        this.timeoutMs = config.timeoutMs
        this.maxBodyBytes = config.maxBodyBytes
        this.fetch = config.fetch ?? internalFetch
        this.dnsResolve = config.dnsResolve ?? defaultDnsResolve

        const parsed = new URL(config.baseUrl)
        this.hostname = parsed.hostname
        this.port = parsed.port || '8080'
    }

    /**
     * Resolve the base URL hostname to IP addresses via DNS. For headless
     * K8s Services this returns all pod IPs; for ClusterIP services or
     * localhost it returns a single IP. Returns sorted for deterministic
     * consistent hashing across consumer pods.
     */
    private async resolveEndpoints(): Promise<string[]> {
        const ips = await this.dnsResolve(this.hostname)
        return ips.sort()
    }

    /**
     * Process a batch of exception events through Cymbal.
     *
     * Resolves DNS to discover Cymbal endpoints. When multiple endpoints
     * are found (headless service), groups events by team_id and routes
     * each group to its consistent pod in parallel. Within each group,
     * uses estimated byte sizes (from the original Kafka messages) to
     * proactively split requests that would exceed Cymbal's body size limit.
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

        const endpoints = await this.resolveEndpoints()

        // Single endpoint (ClusterIP service or local dev) — no grouping needed
        if (endpoints.length === 1) {
            return this.processExceptionsToUrl(`http://${endpoints[0]}:${this.port}`, items)
        }

        // Multiple endpoints (headless service) — route each item to a pod by
        // team_id, then group by destination pod so we make one HTTP call per pod
        const podGroups = new Map<number, { index: number; item: (typeof items)[0] }[]>()
        for (let i = 0; i < items.length; i++) {
            const podIndex = jumpConsistentHash(items[i].request.team_id, endpoints.length)
            let group = podGroups.get(podIndex)
            if (!group) {
                group = []
                podGroups.set(podIndex, group)
            }
            group.push({ index: i, item: items[i] })
        }

        cymbalRoutingGroupsHistogram.observe(podGroups.size)

        // Send each pod's batch in parallel
        const results = new Array<CymbalResponse | null>(items.length)
        await Promise.all(
            Array.from(podGroups.entries()).map(async ([podIndex, group]) => {
                const url = `http://${endpoints[podIndex]}:${this.port}`
                const groupItems = group.map((g) => g.item)
                const responses = await this.processExceptionsToUrl(url, groupItems)
                for (let i = 0; i < responses.length; i++) {
                    results[group[i].index] = responses[i]
                }
            })
        )

        return results
    }

    /**
     * Process items against a specific Cymbal URL, with size-based chunking.
     */
    private async processExceptionsToUrl(
        url: string,
        items: { request: CymbalRequest; estimatedSize: number }[]
    ): Promise<(CymbalResponse | null)[]> {
        const chunks = this.chunkByEstimatedSize(items)
        cymbalChunksPerGroupHistogram.observe(chunks.length)
        const allResults: (CymbalResponse | null)[] = []

        for (const chunk of chunks) {
            const results = await this.processChunk(
                url,
                chunk.map((item) => item.request)
            )
            allResults.push(...results)
        }

        return allResults
    }

    /**
     * Process a single chunk of requests through Cymbal's HTTP API.
     */
    private async processChunk(url: string, requests: CymbalRequest[]): Promise<(CymbalResponse | null)[]> {
        const { response, durationMs } = await this.makeRequest(url, requests)

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
    private async makeRequest(
        url: string,
        requests: CymbalRequest[]
    ): Promise<{ response: FetchResponse; durationMs: number }> {
        const startTime = performance.now()
        try {
            const response = await this.fetch(`${url}/process`, {
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
            const response = await this.fetch(`http://${this.hostname}:${this.port}/_liveness`, {
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

async function defaultDnsResolve(hostname: string): Promise<string[]> {
    return dns.resolve4(hostname)
}
