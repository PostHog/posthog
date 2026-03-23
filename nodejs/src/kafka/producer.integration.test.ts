import * as net from 'net'
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

/** Find a port in 49152-60000 that has nothing listening. */
function findClosedPort(): Promise<number> {
    return new Promise((resolve, reject) => {
        const tryPort = (port: number) => {
            if (port > 60000) {
                reject(new Error('Could not find a closed port'))
                return
            }
            const socket = new net.Socket()
            socket.setTimeout(200)
            socket.once('connect', () => {
                socket.destroy()
                tryPort(port + 1) // port is open, try next
            })
            socket.once('timeout', () => {
                socket.destroy()
                resolve(port) // nothing listening
            })
            socket.once('error', () => {
                socket.destroy()
                resolve(port) // connection refused = nothing listening
            })
            socket.connect(port, 'localhost')
        }
        // Start from a random offset to avoid collisions between test runs
        const start = 49152 + Math.floor(Math.random() * 5000)
        tryPort(start)
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

describe('KafkaProducerWrapper.checkConnection', () => {
    it('succeeds for a reachable broker', async () => {
        const producer = await KafkaProducerWrapper.create(undefined)
        try {
            await expect(producer.checkConnection()).resolves.toBeUndefined()
        } finally {
            await producer.disconnect()
        }
    })

    it('fails to connect to an unreachable broker', async () => {
        const closedPort = await findClosedPort()

        // rdkafka's connect() retries indefinitely — it never rejects.
        // We race against a timeout to verify the connection doesn't succeed.
        const createPromise = KafkaProducerWrapper.createWithConfig(undefined, {
            'metadata.broker.list': `localhost:${closedPort}`,
            'socket.connection.setup.timeout.ms': 1000,
            'reconnect.backoff.max.ms': 100,
        })

        const timeout = new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('Connection failed as expected')), 3000)
        )

        await expect(Promise.race([createPromise, timeout])).rejects.toThrow('Connection failed as expected')
    })
})
