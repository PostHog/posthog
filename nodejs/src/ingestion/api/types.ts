/**
 * A Kafka message as the Rust consumer hands it to the worker. Values are raw
 * UTF-8 strings since PostHog Kafka messages are always JSON-encoded text.
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
