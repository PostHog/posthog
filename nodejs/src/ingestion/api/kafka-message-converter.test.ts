import { deserializeKafkaMessage } from './kafka-message-converter'
import { ProtoKafkaMessage } from './types'

function makeProtoMessage(
    overrides: Partial<ProtoKafkaMessage> & Pick<ProtoKafkaMessage, 'topic' | 'partition' | 'offset'>
): ProtoKafkaMessage {
    return {
        headers: [],
        ...overrides,
    }
}

describe('kafka-message-converter', () => {
    describe('deserializeKafkaMessage', () => {
        const testCases: Array<{ name: string; proto: ProtoKafkaMessage; expected: Record<string, any> }> = [
            {
                name: 'full message with all fields',
                proto: makeProtoMessage({
                    topic: 'events_plugin_ingestion',
                    partition: 3,
                    offset: 12345,
                    timestamp: 1708012800000,
                    key: Buffer.from('phc_abc:user-1'),
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                    headers: [
                        { key: 'token', value: Buffer.from('phc_abc') },
                        { key: 'distinct_id', value: Buffer.from('user-1') },
                    ],
                }),
                expected: {
                    topic: 'events_plugin_ingestion',
                    partition: 3,
                    offset: 12345,
                    timestamp: 1708012800000,
                    hasKey: true,
                    hasValue: true,
                    headerCount: 2,
                },
            },
            {
                name: 'null key and value',
                proto: makeProtoMessage({
                    topic: 'test-topic',
                    partition: 0,
                    offset: 0,
                }),
                expected: {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 0,
                    hasKey: false,
                    hasValue: false,
                    headerCount: 0,
                },
            },
            {
                name: 'binary payload with non-UTF8 bytes',
                proto: makeProtoMessage({
                    topic: 'test-topic',
                    partition: 1,
                    offset: 99,
                    key: Buffer.from([0x00, 0xff, 0x80, 0x7f]),
                    value: Buffer.from([0xde, 0xad, 0xbe, 0xef]),
                    headers: [{ key: 'binary_header', value: Buffer.from([0x01, 0x02, 0x03]) }],
                }),
                expected: {
                    topic: 'test-topic',
                    partition: 1,
                    offset: 99,
                    hasKey: true,
                    hasValue: true,
                    headerCount: 1,
                },
            },
            {
                name: 'multiple headers preserved in order',
                proto: makeProtoMessage({
                    topic: 'test-topic',
                    partition: 0,
                    offset: 5,
                    value: Buffer.from('test'),
                    headers: [
                        { key: 'token', value: Buffer.from('phc_abc') },
                        { key: 'distinct_id', value: Buffer.from('user-1') },
                        { key: 'uuid', value: Buffer.from('550e8400-e29b-41d4-a716-446655440000') },
                        { key: 'event', value: Buffer.from('$pageview') },
                    ],
                }),
                expected: {
                    topic: 'test-topic',
                    partition: 0,
                    offset: 5,
                    hasKey: false,
                    hasValue: true,
                    headerCount: 4,
                },
            },
        ]

        it.each(testCases)('converts proto to Message: $name', ({ proto, expected }) => {
            const result = deserializeKafkaMessage(proto)

            expect(result.topic).toBe(expected.topic)
            expect(result.partition).toBe(expected.partition)
            expect(result.offset).toBe(expected.offset)

            if (expected.hasKey) {
                expect(Buffer.isBuffer(result.key)).toBe(true)
                expect(Buffer.compare(result.key as Buffer, proto.key!)).toBe(0)
            } else {
                expect(result.key).toBeUndefined()
            }

            if (expected.hasValue) {
                expect(Buffer.isBuffer(result.value)).toBe(true)
                expect(Buffer.compare(result.value!, proto.value!)).toBe(0)
            } else {
                expect(result.value).toBeNull()
            }

            expect(result.headers).toHaveLength(expected.headerCount)
            for (let i = 0; i < proto.headers.length; i++) {
                const h = proto.headers[i]
                const resultH = result.headers![i]
                expect(Buffer.compare(resultH[h.key] as Buffer, h.value)).toBe(0)
            }
        })

        it('computes size from value length', () => {
            const proto = makeProtoMessage({
                topic: 'test',
                partition: 0,
                offset: 0,
                value: Buffer.from('hello world'),
            })

            const result = deserializeKafkaMessage(proto)
            expect(result.size).toBe(11)
        })

        it('sets size to 0 for missing value', () => {
            const proto = makeProtoMessage({
                topic: 'test',
                partition: 0,
                offset: 0,
            })

            const result = deserializeKafkaMessage(proto)
            expect(result.size).toBe(0)
        })

        it('converts Long-like offset and timestamp to number', () => {
            const proto = makeProtoMessage({
                topic: 'test',
                partition: 0,
                offset: 12345,
                timestamp: 1708012800000,
                value: Buffer.from('data'),
            })

            const result = deserializeKafkaMessage(proto)
            expect(typeof result.offset).toBe('number')
            expect(result.offset).toBe(12345)
            expect(typeof result.timestamp).toBe('number')
            expect(result.timestamp).toBe(1708012800000)
        })
    })
})
