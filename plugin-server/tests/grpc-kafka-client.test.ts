import { KafkaConsumer, Message } from 'node-rdkafka'

import { parseJSON } from '~/utils/json-parse'

import { GrpcKafkaProducer, createGrpcKafkaProducer } from '../src/kafka/grpc-kafka-client'

const KAFKA_BROKERS = process.env.KAFKA_HOSTS || 'localhost:9092'
const GRPC_SIDECAR_URL = process.env.GRPC_SIDECAR_URL || 'http://localhost:50051'

describe('GrpcKafkaProducer Integration Tests', () => {
    let producer: GrpcKafkaProducer
    let consumer: KafkaConsumer | null = null

    beforeAll(() => {
        producer = createGrpcKafkaProducer({ sidecarUrl: GRPC_SIDECAR_URL })
    })

    afterEach(() => {
        if (consumer) {
            consumer.disconnect()
            consumer = null
        }
    })

    function createConsumer(groupId: string, topic: string): Promise<KafkaConsumer> {
        return new Promise((resolve, reject) => {
            const cons = new KafkaConsumer(
                {
                    'group.id': groupId,
                    'metadata.broker.list': KAFKA_BROKERS,
                    'enable.auto.commit': false,
                },
                {
                    'auto.offset.reset': 'earliest', // Start from beginning for new consumer groups
                }
            )

            cons.connect()

            cons.on('ready', () => {
                cons.subscribe([topic])
                resolve(cons)
            })

            cons.on('event.error', (err) => {
                reject(err)
            })

            // Set timeout for connection
            setTimeout(() => reject(new Error('Consumer connection timeout')), 10000)
        })
    }

    async function consumeMessages(
        consumer: KafkaConsumer,
        count: number,
        timeoutMs: number = 10000
    ): Promise<Message[]> {
        const messages: Message[] = []
        const startTime = Date.now()

        while (messages.length < count) {
            if (Date.now() - startTime > timeoutMs) {
                throw new Error(`Timeout waiting for ${count} messages, got ${messages.length}`)
            }

            // Poll for messages with callback
            const batch = await new Promise<Message[]>((resolve, reject) => {
                consumer.consume(10, (err, msgs) => {
                    if (err) {
                        reject(err)
                    } else {
                        resolve(msgs || [])
                    }
                })
            })

            messages.push(...batch)

            // Small delay between polls if we didn't get enough messages
            if (messages.length < count) {
                await new Promise((resolve) => setTimeout(resolve, 100))
            }
        }

        return messages.slice(0, count)
    }

    it('should produce a message via gRPC and verify in Kafka', async () => {
        const topic = `test-grpc-produce-${Date.now()}`
        const testMessage = { hello: 'world', timestamp: Date.now() }

        // Produce message via gRPC first (this will create the topic)
        const offset = await producer.produce({
            topic,
            value: JSON.stringify(testMessage),
            key: 'test-key',
            headers: {
                'content-type': 'application/json',
                'test-header': 'test-value',
            },
        })

        expect(offset).toBeGreaterThanOrEqual(0n)

        // Now create consumer and verify message
        consumer = await createConsumer(`test-group-${Date.now()}`, topic)

        // Small delay to ensure subscription is active
        await new Promise((resolve) => setTimeout(resolve, 500))

        // Verify message was written to Kafka
        const messages = await consumeMessages(consumer, 1)

        expect(messages).toHaveLength(1)
        expect(messages[0].value?.toString()).toBe(JSON.stringify(testMessage))
        expect(messages[0].key?.toString()).toBe('test-key')
    }, 20000)

    it('should produce a message with Buffer value', async () => {
        const topic = `test-grpc-buffer-${Date.now()}`
        const testBuffer = Buffer.from('binary data here')

        const offset = await producer.produce({
            topic,
            value: testBuffer,
        })

        expect(offset).toBeGreaterThanOrEqual(0n)

        // Verify in Kafka
        consumer = await createConsumer(`test-group-${Date.now()}`, topic)
        await new Promise((resolve) => setTimeout(resolve, 500))

        const messages = await consumeMessages(consumer, 1)

        expect(messages).toHaveLength(1)
        expect(messages[0].value).toEqual(testBuffer)
    }, 20000)

    it('should produce a message with null key', async () => {
        const topic = `test-grpc-no-key-${Date.now()}`
        const testValue = 'message without key'

        const offset = await producer.produce({
            topic,
            value: testValue,
        })

        expect(offset).toBeGreaterThanOrEqual(0n)

        // Verify in Kafka
        consumer = await createConsumer(`test-group-${Date.now()}`, topic)
        await new Promise((resolve) => setTimeout(resolve, 500))

        const messages = await consumeMessages(consumer, 1)

        expect(messages).toHaveLength(1)
        expect(messages[0].value?.toString()).toBe(testValue)
        expect(messages[0].key).toBeNull()
    }, 20000)

    it('should handle multiple concurrent messages', async () => {
        const topic = `test-grpc-concurrent-${Date.now()}`
        const messageCount = 100

        // Produce messages concurrently
        const producePromises = Array.from({ length: messageCount }, (_, i) =>
            producer.produce({
                topic,
                value: JSON.stringify({ index: i }),
                key: `key-${i}`,
            })
        )

        const offsets = await Promise.all(producePromises)
        expect(offsets).toHaveLength(messageCount)
        offsets.forEach((offset) => {
            expect(offset).toBeGreaterThanOrEqual(0n)
        })

        // Verify all messages in Kafka
        consumer = await createConsumer(`test-group-${Date.now()}`, topic)
        await new Promise((resolve) => setTimeout(resolve, 500))

        const messages = await consumeMessages(consumer, messageCount, 30000)

        expect(messages).toHaveLength(messageCount)

        // Verify message content
        const indices = messages.map((m) => parseJSON(m.value!.toString()).index).sort((a, b) => a - b)
        expect(indices).toEqual(Array.from({ length: messageCount }, (_, i) => i))
    }, 60000)
})
