import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { SerializedKafkaMessage } from './types'

const outOfOrderMessages = new Counter({
    name: 'ingestion_api_out_of_order_messages_total',
    help: 'Messages fed to the pipeline at or below their routing key’s last seen offset, outside a marked replay — a per-key ordering violation',
})

const replayedMessages = new Counter({
    name: 'ingestion_api_replayed_messages_total',
    help: 'Messages at or below their routing key’s last seen offset inside a marked replay request — expected at-least-once redelivery, not a violation',
})

const sentinelKeys = new Gauge({
    name: 'ingestion_api_order_sentinel_keys',
    help: 'Routing keys currently tracked by the feed-order sentinel',
})

const sentinelEvictions = new Counter({
    name: 'ingestion_api_order_sentinel_evictions_total',
    help: 'Routing keys evicted from the feed-order sentinel at capacity (their next appearance rebaselines unchecked)',
})

export interface FeedOrderCheckResult {
    outOfOrder: number
    replayed: number
}

interface KeyEntry {
    consumerId: string
    offset: number
}

/**
 * Verifies the pipeline's per-key ordering invariant at its measurement point:
 * the feed. The grouping stage processes each routing key's messages strictly
 * in feed order, so "fed in Kafka offset order per key" is exactly "processed
 * in order per key". Call `check` synchronously immediately before
 * `pipeline.feed()` — the shared event loop then makes check order identical
 * to feed order even with concurrent /ingest requests.
 *
 * The Rust consumer stamps each request with its process incarnation
 * (`consumer_id`) and a `replay` flag (HTTP retry or deferred-flush re-route).
 * An offset regression within one incarnation is an ordering violation unless
 * the request is a replay (at-least-once redelivery of un-ACKed messages). A
 * changed incarnation (consumer restart or partition handoff) legitimately
 * replays uncommitted offsets, so the key rebaselines instead of firing.
 *
 * State is a bounded LRU: at capacity the least-recently-seen key is dropped
 * and its next appearance rebaselines unchecked (sampling, not a guarantee
 * gap under normal cardinality).
 */
export class FeedOrderSentinel {
    private entries = new Map<string, KeyEntry>()

    constructor(private readonly maxKeys: number = 200_000) {}

    check(messages: SerializedKafkaMessage[], consumerId: string, replay: boolean): FeedOrderCheckResult {
        const result: FeedOrderCheckResult = { outOfOrder: 0, replayed: 0 }

        for (const message of messages) {
            const token = message.headers['token']
            const distinctId = message.headers['distinct_id']
            if (!token || !distinctId) {
                // No routing key: the consumer routes these individually under a
                // synthetic unique key, so there is no per-key order to check.
                continue
            }
            const key = `${message.topic}/${message.partition}/${token}:${distinctId}`

            const entry = this.entries.get(key)
            if (entry && entry.consumerId === consumerId) {
                if (message.offset <= entry.offset) {
                    if (replay) {
                        result.replayed++
                    } else {
                        result.outOfOrder++
                        logger.warn('⚠️', 'Out-of-order message fed to ingestion pipeline', {
                            key,
                            offset: message.offset,
                            lastSeenOffset: entry.offset,
                            consumerId,
                        })
                    }
                } else {
                    entry.offset = message.offset
                }
                // Refresh LRU recency (Map preserves insertion order).
                this.entries.delete(key)
                this.entries.set(key, entry)
            } else {
                // New key, or a new consumer incarnation: rebaseline.
                this.entries.delete(key)
                this.entries.set(key, { consumerId, offset: message.offset })
            }
        }

        let evicted = 0
        while (this.entries.size > this.maxKeys) {
            const oldest = this.entries.keys().next().value
            if (oldest === undefined) {
                break
            }
            this.entries.delete(oldest)
            evicted++
        }

        if (result.outOfOrder > 0) {
            outOfOrderMessages.inc(result.outOfOrder)
        }
        if (result.replayed > 0) {
            replayedMessages.inc(result.replayed)
        }
        if (evicted > 0) {
            sentinelEvictions.inc(evicted)
        }
        sentinelKeys.set(this.entries.size)

        return result
    }

    get size(): number {
        return this.entries.size
    }
}
