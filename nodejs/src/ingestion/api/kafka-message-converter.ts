import { Message, MessageHeader } from 'node-rdkafka'

import { ProtoKafkaMessage } from './types'

export function deserializeKafkaMessage(msg: ProtoKafkaMessage): Message {
    const headers: MessageHeader[] = msg.headers.map((h) => ({
        [h.key]: Buffer.from(h.value),
    }))

    const value = msg.value?.length ? Buffer.from(msg.value) : null

    return {
        topic: msg.topic,
        partition: msg.partition,
        offset: Number(msg.offset),
        timestamp: msg.timestamp ? Number(msg.timestamp) : undefined,
        key: msg.key?.length ? Buffer.from(msg.key) : undefined,
        value,
        size: value?.length ?? 0,
        headers,
    }
}
