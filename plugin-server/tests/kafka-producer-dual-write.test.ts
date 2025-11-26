import { KafkaConsumer, Message } from 'node-rdkafka'

import { defaultConfig } from '../src/config/config'
import { KafkaProducerWrapper } from '../src/kafka/producer'

const KAFKA_BROKERS = process.env.KAFKA_HOSTS || 'localhost:9092'

describe('KafkaProducerWrapper topic suffix integration', () => {
    jest.setTimeout(60000)
    let producer: KafkaProducerWrapper
    let nodeConsumer: KafkaConsumer | null = null
    let sidecarConsumer: KafkaConsumer | null = null

    afterEach(async () => {
        if (nodeConsumer) {
            nodeConsumer.disconnect()
            nodeConsumer = null
        }
        if (sidecarConsumer) {
            sidecarConsumer.disconnect()
            sidecarConsumer = null
        }
        if (producer) {
            await producer.disconnect()
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
                    'auto.offset.reset': 'earliest',
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

            if (messages.length < count) {
                await new Promise((resolve) => setTimeout(resolve, 100))
            }
        }

        return messages.slice(0, count)
    }

    it('should produce to different topics when suffix is configured in both mode', async () => {
        const baseTopic = `test-suffix-${Date.now()}`
        const sidecarTopic = `${baseTopic}_sidecar`
        const testMessage = { hello: 'world', test: 'suffix' }

        producer = await KafkaProducerWrapper.create({
            ...defaultConfig,
            PRODUCE_KAFKA_MODE: 'both',
            GRPC_SIDECAR_URL: 'http://localhost:50051',
            GRPC_SIDECAR_TOPIC_SUFFIX: '_sidecar',
            KAFKA_HOSTS: KAFKA_BROKERS,
        })

        await producer.produce({
            topic: baseTopic,
            value: Buffer.from(JSON.stringify(testMessage)),
            key: Buffer.from('test-key'),
        })

        nodeConsumer = await createConsumer(`test-node-${Date.now()}`, baseTopic)
        sidecarConsumer = await createConsumer(`test-sidecar-${Date.now()}`, sidecarTopic)

        await new Promise((resolve) => setTimeout(resolve, 500))

        const nodeMessages = await consumeMessages(nodeConsumer, 1, 15000)
        expect(nodeMessages).toHaveLength(1)
        expect(nodeMessages[0].value?.toString()).toBe(JSON.stringify(testMessage))
        expect(nodeMessages[0].key?.toString()).toBe('test-key')

        const sidecarMessages = await consumeMessages(sidecarConsumer, 1, 15000)
        expect(sidecarMessages).toHaveLength(1)
        expect(sidecarMessages[0].value?.toString()).toBe(JSON.stringify(testMessage))
        expect(sidecarMessages[0].key?.toString()).toBe('test-key')
    })

    it('should produce to same topic when suffix is empty in both mode', async () => {
        const baseTopic = `test-no-suffix-${Date.now()}`
        const testMessage = { hello: 'world', test: 'no-suffix' }

        producer = await KafkaProducerWrapper.create({
            ...defaultConfig,
            PRODUCE_KAFKA_MODE: 'both',
            GRPC_SIDECAR_URL: 'http://localhost:50051',
            GRPC_SIDECAR_TOPIC_SUFFIX: '',
            KAFKA_HOSTS: KAFKA_BROKERS,
        })

        await producer.produce({
            topic: baseTopic,
            value: Buffer.from(JSON.stringify(testMessage)),
            key: Buffer.from('test-key'),
        })

        nodeConsumer = await createConsumer(`test-both-${Date.now()}`, baseTopic)
        await new Promise((resolve) => setTimeout(resolve, 500))

        const messages = await consumeMessages(nodeConsumer, 2, 15000)
        expect(messages).toHaveLength(2)

        messages.forEach((msg) => {
            expect(msg.value?.toString()).toBe(JSON.stringify(testMessage))
            expect(msg.key?.toString()).toBe('test-key')
        })
    })
})
