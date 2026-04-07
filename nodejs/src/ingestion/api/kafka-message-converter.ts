import { Message, MessageHeader } from 'node-rdkafka'

import { SerializedKafkaMessage } from './types'

/**
 * Converts a SerializedKafkaMessage (from the Rust consumer HTTP API)
 * back into a node-rdkafka Message for the ingestion pipeline.
 */
export function deserializeKafkaMessage(serialized: SerializedKafkaMessage): Message {
    const headers: MessageHeader[] = Object.entries(serialized.headers).map(([key, value]) => ({
        [key]: Buffer.from(value, 'utf-8'),
    }))

    return {
        topic: serialized.topic,
        partition: serialized.partition,
        offset: serialized.offset,
        timestamp: serialized.timestamp,
        size: serialized.value?.length ?? 0,
        key: serialized.key ? Buffer.from(serialized.key, 'utf-8') : undefined,
        value: serialized.value ? Buffer.from(serialized.value, 'utf-8') : null,
        headers: headers.length > 0 ? headers : undefined,
    }
}
