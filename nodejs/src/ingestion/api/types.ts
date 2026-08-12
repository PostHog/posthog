/**
 * Wire types for the ingestion worker HTTP API.
 *
 * These types define the contract between the Rust Kafka consumer
 * and Node.js worker processes. Values are passed as raw UTF-8 strings
 * since PostHog Kafka messages are always JSON-encoded text.
 */

export interface SerializedKafkaMessage {
    topic: string
    partition: number
    offset: number
    timestamp: number
    key: string | null
    value: string | null
    headers: Record<string, string>
}

export interface IngestBatchRequest {
    batch_id: string
    messages: SerializedKafkaMessage[]
    /** Consumer process incarnation; the feed-order sentinel rebaselines a key when it changes. Optional for older consumers. */
    consumer_id?: string
    /** True when the request may repeat previously sent messages (HTTP retry or deferred-flush re-route). */
    replay?: boolean
}

export interface IngestBatchResponse {
    batch_id: string
    status: 'ok' | 'error'
    accepted: number
    error?: string
}
