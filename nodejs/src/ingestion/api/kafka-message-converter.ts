import { Message, MessageHeader } from 'node-rdkafka'

import { SerializedKafkaMessage } from './types'

export function serializeKafkaMessage(msg: Message): SerializedKafkaMessage {
    const headers: Array<Record<string, string>> = []
    if (msg.headers) {
        for (const header of msg.headers) {
            for (const [key, val] of Object.entries(header)) {
                const buf = Buffer.isBuffer(val) ? val : Buffer.from(val)
                headers.push({ [key]: buf.toString('base64') })
            }
        }
    }

    return {
        topic: msg.topic,
        partition: msg.partition,
        offset: msg.offset,
        timestamp: msg.timestamp,
        key: msg.key != null ? (Buffer.isBuffer(msg.key) ? msg.key : Buffer.from(msg.key)).toString('base64') : null,
        value: msg.value != null ? msg.value.toString('base64') : null,
        headers,
    }
}

export function deserializeKafkaMessage(msg: SerializedKafkaMessage): Message {
    const headers: MessageHeader[] = []
    for (const header of msg.headers) {
        for (const [key, val] of Object.entries(header)) {
            headers.push({ [key]: Buffer.from(val, 'base64') })
        }
    }

    const value = msg.value != null ? Buffer.from(msg.value, 'base64') : null

    return {
        topic: msg.topic,
        partition: msg.partition,
        offset: msg.offset,
        timestamp: msg.timestamp,
        key: msg.key != null ? Buffer.from(msg.key, 'base64') : undefined,
        value,
        size: value?.length ?? 0,
        headers,
    }
}
