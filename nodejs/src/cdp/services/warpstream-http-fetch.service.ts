import { Counter, Histogram } from 'prom-client'

import { logger } from '../../utils/logger'
import { internalFetch } from '../../utils/request'

const counterFetchRequests = new Counter({
    name: 'cdp_warpstream_http_fetch_requests_total',
    help: 'Warpstream HTTP fetch requests issued, by outcome.',
    labelNames: ['outcome'],
})

const counterRecordsFetched = new Counter({
    name: 'cdp_warpstream_http_fetch_records_total',
    help: 'Records returned across Warpstream HTTP fetch requests.',
})

const histogramFetchDuration = new Histogram({
    name: 'cdp_warpstream_http_fetch_duration_ms',
    help: 'Duration of a full (possibly multi-round) Warpstream HTTP fetch resolve, in ms.',
    buckets: [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

export interface RecordRef {
    partition: number
    offset: number
}

/** Subset of the Warpstream `/v1/kafka/fetch` response we read. */
interface WarpstreamFetchResponse {
    topics?: {
        topic: string
        partitions?: {
            partition: number
            error_code?: number
            high_watermark?: number
            records?: { offset: number; value: string | null }[]
        }[]
    }[]
}

export interface WarpstreamHttpFetchConfig {
    /** Base URL of a Warpstream agent HTTP endpoint, e.g. http://agent:8080. */
    url: string
    username: string
    password: string
}

// Per-partition byte budget for a single fetch round. The records we read are
// gzip+base64'd globals, typically well under this — generous so a round pulls
// a long contiguous run of offsets in one go.
const PARTITION_MAX_BYTES = 8 * 1024 * 1024
// Bound on fetch rounds per resolve. A page's offsets within a partition are
// roughly contiguous (a contiguous scheduled-time window produced in order), so
// a handful of rounds covers the spread; the cap stops a pathological sparse
// spread from looping unbounded.
const MAX_ROUNDS = 8
const REQUEST_TIMEOUT_MS = 15_000

const refKey = (partition: number, offset: number): string => `${partition}:${offset}`

/**
 * Reads individual Kafka records back by (partition, offset) via a Warpstream
 * agent's HTTP fetch endpoint. Used by the rerun path to resolve a row's
 * `invocation_globals` from the results topic instead of from a persisted
 * ClickHouse column.
 *
 * The fetch protocol takes a single start offset per partition (not a set), so
 * `fetchRecords` groups the wanted offsets by partition, fetches from the lowest
 * outstanding offset in each, indexes the returned records by offset, and
 * repeats for any offsets the byte/record budget didn't reach — batching every
 * partition into one HTTP request per round.
 */
export class WarpstreamHttpFetchService {
    constructor(
        private config: WarpstreamHttpFetchConfig,
        // `internalFetch` skips the SSRF guard — the agent is an internal service.
        private fetchImpl: typeof internalFetch = internalFetch
    ) {}

    private get endpoint(): string {
        return `${this.config.url.replace(/\/$/, '')}/v1/kafka/fetch`
    }

    private get authHeader(): Record<string, string> {
        if (!this.config.username && !this.config.password) {
            return {}
        }
        const token = Buffer.from(`${this.config.username}:${this.config.password}`).toString('base64')
        return { authorization: `Basic ${token}` }
    }

    /**
     * Fetch the records at the exact `(partition, offset)` refs from `topic`.
     * Returns a map keyed by `"partition:offset"` of the raw record value
     * (base64-decoded to a Buffer). Refs whose record can't be retrieved (aged
     * out of retention, or beyond the round budget) are simply absent — callers
     * decide how to handle a miss.
     */
    async fetchRecords(topic: string, refs: RecordRef[]): Promise<Map<string, Buffer>> {
        const out = new Map<string, Buffer>()
        if (refs.length === 0) {
            return out
        }
        const end = histogramFetchDuration.startTimer()

        // partition -> sorted unique outstanding offsets we still need.
        const wantedByPartition = new Map<number, number[]>()
        for (const ref of refs) {
            const list = wantedByPartition.get(ref.partition) ?? []
            list.push(ref.offset)
            wantedByPartition.set(ref.partition, list)
        }
        for (const [partition, offsets] of wantedByPartition) {
            wantedByPartition.set(
                partition,
                [...new Set(offsets)].sort((a, b) => a - b)
            )
        }

        try {
            for (let round = 0; round < MAX_ROUNDS; round++) {
                const partitions = [...wantedByPartition.entries()]
                    .filter(([, offsets]) => offsets.length > 0)
                    .map(([partition, offsets]) => ({
                        partition,
                        fetch_offset: offsets[0],
                        partition_max_bytes: PARTITION_MAX_BYTES,
                    }))
                if (partitions.length === 0) {
                    break
                }

                const response: WarpstreamFetchResponse | null = await this.fetchOnce(topic, partitions)
                if (!response) {
                    break
                }

                let madeProgress = false
                for (const t of response.topics ?? []) {
                    for (const p of t.partitions ?? []) {
                        const wanted = wantedByPartition.get(p.partition)
                        if (!wanted || wanted.length === 0) {
                            continue
                        }
                        const wantedSet = new Set(wanted)
                        let maxReturnedOffset = -1
                        for (const record of p.records ?? []) {
                            maxReturnedOffset = Math.max(maxReturnedOffset, record.offset)
                            if (wantedSet.has(record.offset) && record.value != null) {
                                out.set(refKey(p.partition, record.offset), Buffer.from(record.value, 'base64'))
                                counterRecordsFetched.inc()
                                madeProgress = true
                            }
                        }
                        // Drop any wanted offset we've now passed: either we got
                        // it, or it's a gap before the furthest record this round
                        // returned (so it'll never appear). Offsets beyond the
                        // round's reach stay outstanding for the next round.
                        const remaining = wanted.filter(
                            (o) => !out.has(refKey(p.partition, o)) && o > maxReturnedOffset
                        )
                        wantedByPartition.set(p.partition, remaining)
                    }
                }

                if (!madeProgress) {
                    break
                }
            }

            counterFetchRequests.labels('ok').inc()
            return out
        } catch (e) {
            counterFetchRequests.labels('error').inc()
            logger.warn('⚠️', `Warpstream HTTP fetch failed: ${e instanceof Error ? e.message : String(e)}`)
            return out
        } finally {
            end()
        }
    }

    private async fetchOnce(
        topic: string,
        partitions: { partition: number; fetch_offset: number; partition_max_bytes: number }[]
    ): Promise<WarpstreamFetchResponse | null> {
        const res = await this.fetchImpl(this.endpoint, {
            method: 'POST',
            headers: { 'content-type': 'application/json', ...this.authHeader },
            body: JSON.stringify({
                max_bytes: PARTITION_MAX_BYTES,
                topics: [{ topic, partitions }],
            }),
            timeoutMs: REQUEST_TIMEOUT_MS,
        })
        if (res.status < 200 || res.status >= 300) {
            logger.warn('⚠️', `Warpstream HTTP fetch returned ${res.status}`)
            return null
        }
        return (await res.json()) as WarpstreamFetchResponse
    }
}
