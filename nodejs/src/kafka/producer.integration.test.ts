import { AdminClient, LibrdKafkaError } from 'node-rdkafka'

import { createTopics } from '../../tests/helpers/kafka'
import { KafkaProducerWrapper } from './producer'

jest.setTimeout(30000)

const KAFKA_CONFIG = { 'metadata.broker.list': 'kafka:9092' }

function deleteTopic(topic: string): Promise<void> {
    const client = AdminClient.create(KAFKA_CONFIG)
    return new Promise<void>((resolve) => {
        client.deleteTopic(topic, 10000, (_error: LibrdKafkaError) => {
            client.disconnect()
            resolve() // ignore errors — topic may not exist
        })
    })
}

describe('KafkaProducerWrapper.checkTopicExists', () => {
    let producer: KafkaProducerWrapper
    const topicExists = 'check_topic_exists_test'
    const topicMissing = 'check_topic_missing_test'

    beforeAll(async () => {
        producer = await KafkaProducerWrapper.create(undefined)

        await deleteTopic(topicExists)
        await deleteTopic(topicMissing)
        await createTopics(KAFKA_CONFIG, [topicExists])
    })

    afterAll(async () => {
        await producer.disconnect()
        await deleteTopic(topicExists)
    })

    it('succeeds for an existing topic', async () => {
        await expect(producer.checkTopicExists(topicExists)).resolves.toBeUndefined()
    })

    it('throws for a non-existent topic', async () => {
        await expect(producer.checkTopicExists(topicMissing)).rejects.toThrow()
    })
})
