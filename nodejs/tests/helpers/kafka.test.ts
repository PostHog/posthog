import { KafkaConsumer } from 'node-rdkafka'

import { TEST_KAFKA_TOPICS, createKafkaTestTopicName, ensureKafkaTopics, resetKafka } from './kafka'

jest.setTimeout(10_000)

const KAFKA_CONFIG = { 'metadata.broker.list': process.env.KAFKA_HOSTS ?? 'kafka:9092' }

async function getTopicNames(): Promise<Set<string>> {
    const consumer = new KafkaConsumer({ ...KAFKA_CONFIG, 'group.id': 'reset-kafka-test' }, {})
    await new Promise<void>((resolve, reject) => {
        consumer.on('ready', resolve)
        consumer.on('event.error', reject)
        consumer.connect()
    })

    try {
        const metadata = await new Promise<{ topics: { name: string }[] }>((resolve, reject) => {
            consumer.getMetadata({}, (error, value) => (error ? reject(error) : resolve(value)))
        })
        return new Set(metadata.topics.map((topic) => topic.name))
    } finally {
        consumer.disconnect()
    }
}

describe('resetKafka', () => {
    it('removes extra topics and restores the shared test topics', async () => {
        const extraTopic = createKafkaTestTopicName('reset-kafka')
        await ensureKafkaTopics([extraTopic])

        await resetKafka()

        const topics = await getTopicNames()
        expect(topics).not.toContain(extraTopic)
        for (const topic of TEST_KAFKA_TOPICS) {
            expect(topics).toContain(topic)
        }
    })
})
