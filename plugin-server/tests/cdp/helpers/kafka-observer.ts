import { KafkaConsumer, Message } from 'node-rdkafka'

import { createAdminClient, ensureTopicExists } from '../../../src/kafka/admin'
import { createRdConnectionConfigFromEnvVars } from '../../../src/kafka/config'
import { createKafkaConsumer } from '../../../src/kafka/consumer'
import { Hub } from '../../../src/types'
import { delay, UUIDT } from '../../../src/utils/utils'

export type TestKafkaObserver = {
    messages: {
        topic: string
        value: any
    }[]
    consumer: KafkaConsumer
    stop: () => Promise<void>
    expectMessageCount: (count: number) => Promise<void>
}

export const createKafkaObserver = async (hub: Hub, topics: string[]): Promise<TestKafkaObserver> => {
    const consumer = await createKafkaConsumer({
        ...createRdConnectionConfigFromEnvVars(hub),
        'group.id': `test-group-${new UUIDT().toString()}`,
    })

    const adminClient = createAdminClient(createRdConnectionConfigFromEnvVars(hub))
    await Promise.all(topics.map((topic) => ensureTopicExists(adminClient, topic, 1000)))
    adminClient.disconnect()

    consumer.connect()
    consumer.subscribe(topics)
    const messages: {
        topic: string
        value: any
    }[] = []

    const poll = async () => {
        await delay(50)
        if (!consumer.isConnected()) {
            return
        }
        const newMessages = await new Promise<Message[]>((res, rej) =>
            consumer.consume(10, (err, messages) => (err ? rej(err) : res(messages)))
        )

        messages.push(
            ...newMessages.map((message) => ({
                topic: message.topic,
                value: JSON.parse(message.value?.toString() ?? ''),
            }))
        )
        poll()
    }

    poll()

    return {
        messages,
        consumer,
        stop: () => new Promise((res) => consumer.disconnect(res)),
        expectMessageCount: async (count: number): Promise<void> => {
            const timeout = 5000
            const now = Date.now()
            while (messages.length < count && Date.now() - now < timeout) {
                await delay(100)
            }

            if (messages.length < count) {
                throw new Error(`Expected ${count} messages, got ${messages.length}`)
            }
        },
    }
}
