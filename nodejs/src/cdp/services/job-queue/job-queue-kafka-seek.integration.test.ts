import { AdminClient, CODES, HighLevelProducer, LibrdKafkaError, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

const TEST_TOPIC = 'test_seek_integration'
const BROKER_LIST = process.env.KAFKA_HOSTS || 'localhost:9092'

const kafkaConfig = {
    'metadata.broker.list': BROKER_LIST,
    'client.id': 'seek-integration-test',
}

async function createTopic(): Promise<void> {
    const admin = AdminClient.create(kafkaConfig)
    await new Promise<void>((resolve, reject) => {
        admin.createTopic(
            { topic: TEST_TOPIC, num_partitions: 1, replication_factor: 1 },
            5000,
            (err: LibrdKafkaError) => {
                if (err && err.code !== CODES.ERRORS.ERR_TOPIC_ALREADY_EXISTS) {
                    reject(err)
                } else {
                    resolve()
                }
            }
        )
    })
    admin.disconnect()
}

async function deleteTopic(): Promise<void> {
    const admin = AdminClient.create(kafkaConfig)
    await new Promise<void>((resolve) => {
        admin.deleteTopic(TEST_TOPIC, 5000, () => resolve())
    })
    admin.disconnect()
}

async function produceMessages(count: number): Promise<{ key: string; value: string; offset: number }[]> {
    const producer = new HighLevelProducer({ ...kafkaConfig, dr_cb: true })

    await new Promise((resolve, reject) => producer.connect({}, (err, data) => (err ? reject(err) : resolve(data))))

    const produced: { key: string; value: string; offset: number }[] = []

    for (let i = 0; i < count; i++) {
        const key = `msg-${i}`
        const value = JSON.stringify({ index: i, payload: `data-${i}`, timestamp: Date.now() })

        const offset = await new Promise<number>((resolve, reject) => {
            producer.produce(TEST_TOPIC, null, Buffer.from(value), Buffer.from(key), Date.now(), [], (err, offset) =>
                err ? reject(err) : resolve(offset as number)
            )
        })

        produced.push({ key, value, offset })
    }

    await new Promise<void>((resolve, reject) => producer.flush(5000, (err) => (err ? reject(err) : resolve())))

    producer.disconnect()
    return produced
}

function createSeekConsumer(): RdKafkaConsumer {
    return new RdKafkaConsumer(
        {
            ...kafkaConfig,
            'group.id': `seek-test-${Date.now()}`,
            'enable.auto.commit': false,
            'enable.auto.offset.store': false,
        },
        { 'auto.offset.reset': 'earliest' }
    )
}

async function connectConsumer(consumer: RdKafkaConsumer): Promise<void> {
    await new Promise((resolve, reject) => consumer.connect({}, (err, data) => (err ? reject(err) : resolve(data))))
    consumer.setDefaultConsumeTimeout(5000)
}

async function seekAndConsume(
    consumer: RdKafkaConsumer,
    partition: number,
    offset: number
): Promise<{ key: string; value: string; offset: number } | null> {
    consumer.assign([{ topic: TEST_TOPIC, partition, offset }])

    const messages = await new Promise<any[]>((resolve, reject) => {
        consumer.consume(1, (err, msgs) => (err ? reject(err) : resolve(msgs)))
    })

    if (messages.length === 0) {
        return null
    }

    return {
        key: messages[0].key?.toString() || '',
        value: messages[0].value?.toString() || '',
        offset: messages[0].offset,
    }
}

describe('Kafka seek-by-offset integration', () => {
    let consumer: RdKafkaConsumer
    let produced: { key: string; value: string; offset: number }[]

    beforeAll(async () => {
        await deleteTopic()
        await createTopic()
        // Small delay for topic to be ready
        await new Promise((r) => setTimeout(r, 1000))

        produced = await produceMessages(20)

        consumer = createSeekConsumer()
        await connectConsumer(consumer)
    }, 30000)

    afterAll(async () => {
        await new Promise<void>((resolve) => consumer.disconnect(() => resolve()))
        await deleteTopic()
    })

    it('should read back the exact message at a given offset', async () => {
        const target = produced[10]
        const result = await seekAndConsume(consumer, 0, target.offset)

        expect(result).not.toBeNull()
        expect(result!.offset).toBe(target.offset)
        expect(result!.key).toBe(target.key)
        expect(result!.value).toBe(target.value)
    })

    it('should read back every produced message by offset', async () => {
        for (const msg of produced) {
            const result = await seekAndConsume(consumer, 0, msg.offset)

            expect(result).not.toBeNull()
            expect(result!.offset).toBe(msg.offset)
            expect(result!.key).toBe(msg.key)
            expect(result!.value).toBe(msg.value)
        }
    })

    it('should return the same message when seeking to the same offset twice', async () => {
        const target = produced[5]

        const first = await seekAndConsume(consumer, 0, target.offset)
        const second = await seekAndConsume(consumer, 0, target.offset)

        expect(first).toEqual(second)
        expect(first!.key).toBe(target.key)
    })

    it('should seek backwards after reading a later offset', async () => {
        const later = await seekAndConsume(consumer, 0, produced[15].offset)
        expect(later!.offset).toBe(produced[15].offset)

        const earlier = await seekAndConsume(consumer, 0, produced[3].offset)
        expect(earlier!.offset).toBe(produced[3].offset)
        expect(earlier!.key).toBe(produced[3].key)
    })

    it('should seek in random order and always return correct data', async () => {
        const indices = [7, 0, 19, 12, 3, 18, 1, 15]

        for (const i of indices) {
            const result = await seekAndConsume(consumer, 0, produced[i].offset)

            expect(result).not.toBeNull()
            expect(result!.offset).toBe(produced[i].offset)
            expect(result!.key).toBe(produced[i].key)
        }
    })
})
