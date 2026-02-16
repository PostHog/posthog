import { Message, MessageHeader } from 'node-rdkafka'

import { deserializeKafkaMessage, serializeKafkaMessage } from './kafka-message-converter'
import { SerializedKafkaMessage } from './types'

function makeHeader(key: string, value: Buffer): MessageHeader {
    const h: MessageHeader = {}
    h[key] = value
    return h
}

function makeMessage(overrides: Partial<Message> & Pick<Message, 'topic' | 'partition' | 'offset' | 'value'>): Message {
    return {
        size: overrides.value?.length ?? 0,
        headers: [],
        ...overrides,
    }
}

describe('kafka-message-converter', () => {
    describe('round-trip serialization', () => {
        const testCases: Array<{ name: string; message: Message }> = [
            {
                name: 'full message with all fields',
                message: makeMessage({
                    topic: 'events_plugin_ingestion',
                    partition: 3,
                    offset: 12345,
                    timestamp: 1708012800000,
                    key: Buffer.from('phc_abc:user-1'),
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                    headers: [
                        makeHeader('token', Buffer.from('phc_abc')),
                        makeHeader('distinct_id', Buffer.from('user-1')),
                    ],
                }),
            },
            {
                name: 'null key and value',
                message: makeMessage({
                    topic: 'test-topic',
                    partition: 0,
                    offset: 0,
                    key: undefined,
                    value: null,
                    headers: [],
                }),
            },
            {
                name: 'binary payload with non-UTF8 bytes',
                message: makeMessage({
                    topic: 'test-topic',
                    partition: 1,
                    offset: 99,
                    key: Buffer.from([0x00, 0xff, 0x80, 0x7f]),
                    value: Buffer.from([0xde, 0xad, 0xbe, 0xef]),
                    headers: [makeHeader('binary_header', Buffer.from([0x01, 0x02, 0x03]))],
                }),
            },
            {
                name: 'multiple headers preserved in order',
                message: makeMessage({
                    topic: 'test-topic',
                    partition: 0,
                    offset: 5,
                    value: Buffer.from('test'),
                    headers: [
                        makeHeader('token', Buffer.from('phc_abc')),
                        makeHeader('distinct_id', Buffer.from('user-1')),
                        makeHeader('uuid', Buffer.from('550e8400-e29b-41d4-a716-446655440000')),
                        makeHeader('event', Buffer.from('$pageview')),
                    ],
                }),
            },
            {
                name: 'no timestamp',
                message: makeMessage({
                    topic: 'test-topic',
                    partition: 2,
                    offset: 7,
                    value: Buffer.from('data'),
                    headers: [],
                }),
            },
            {
                name: 'empty headers array',
                message: makeMessage({
                    topic: 'test-topic',
                    partition: 0,
                    offset: 0,
                    value: Buffer.from('data'),
                    headers: [],
                }),
            },
        ]

        it.each(testCases)('preserves all fields: $name', ({ message }) => {
            const serialized = serializeKafkaMessage(message)
            const deserialized = deserializeKafkaMessage(serialized)

            expect(deserialized.topic).toBe(message.topic)
            expect(deserialized.partition).toBe(message.partition)
            expect(deserialized.offset).toBe(message.offset)
            expect(deserialized.timestamp).toBe(message.timestamp)

            if (message.key != null) {
                const originalKey = Buffer.isBuffer(message.key) ? message.key : Buffer.from(message.key)
                expect(Buffer.isBuffer(deserialized.key)).toBe(true)
                expect(Buffer.compare(deserialized.key as Buffer, originalKey)).toBe(0)
            } else {
                expect(deserialized.key).toBeUndefined()
            }

            if (message.value != null) {
                expect(Buffer.compare(deserialized.value!, message.value)).toBe(0)
            } else {
                expect(deserialized.value).toBeNull()
            }

            expect(deserialized.headers).toHaveLength(message.headers?.length ?? 0)
            if (message.headers) {
                for (let i = 0; i < message.headers.length; i++) {
                    const originalHeader = message.headers[i]
                    const deserializedHeader = deserialized.headers![i]
                    for (const [key, val] of Object.entries(originalHeader)) {
                        const originalBuf = Buffer.isBuffer(val) ? val : Buffer.from(val)
                        expect(Buffer.compare(deserializedHeader[key] as Buffer, originalBuf)).toBe(0)
                    }
                }
            }
        })
    })

    describe('serializeKafkaMessage', () => {
        it('base64 encodes key, value, and header values', () => {
            const msg = makeMessage({
                topic: 'test',
                partition: 0,
                offset: 0,
                key: Buffer.from('my-key'),
                value: Buffer.from('my-value'),
                headers: [makeHeader('token', Buffer.from('phc_abc'))],
            })

            const serialized = serializeKafkaMessage(msg)

            expect(serialized.key).toBe(Buffer.from('my-key').toString('base64'))
            expect(serialized.value).toBe(Buffer.from('my-value').toString('base64'))
            expect(serialized.headers[0]['token']).toBe(Buffer.from('phc_abc').toString('base64'))
        })

        it('handles string header values from node-rdkafka', () => {
            // node-rdkafka can deliver header values as strings at runtime
            const header: MessageHeader = {}
            header['token'] = 'phc_abc'

            const msg = makeMessage({
                topic: 'test',
                partition: 0,
                offset: 0,
                value: null,
                headers: [header],
            })

            const serialized = serializeKafkaMessage(msg)
            expect(serialized.headers[0]['token']).toBe(Buffer.from('phc_abc').toString('base64'))
        })
    })

    describe('deserializeKafkaMessage', () => {
        it('computes size from value length', () => {
            const serialized: SerializedKafkaMessage = {
                topic: 'test',
                partition: 0,
                offset: 0,
                key: null,
                value: Buffer.from('hello world').toString('base64'),
                headers: [],
            }

            const deserialized = deserializeKafkaMessage(serialized)
            expect(deserialized.size).toBe(11)
        })

        it('sets size to 0 for null value', () => {
            const serialized: SerializedKafkaMessage = {
                topic: 'test',
                partition: 0,
                offset: 0,
                key: null,
                value: null,
                headers: [],
            }

            const deserialized = deserializeKafkaMessage(serialized)
            expect(deserialized.size).toBe(0)
        })
    })
})
