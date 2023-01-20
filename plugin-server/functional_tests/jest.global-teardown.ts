import { assert } from 'console'
import { Kafka, logLevel } from 'kafkajs'

import { defaultConfig } from '../src/config/config'

export default async function () {
    // Ensure add consumer groups hae zero lag. This is intended to catch cases
    // where we have managed to process a message but then failed to commit the
    // offset, leaving the consumer group in a bad state.

    const kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })
    const admin = kafka.admin()
    try {
        await admin.connect()
        const topics = await admin.listTopics()
        const topicOffsets = Object.fromEntries(
            await Promise.all(topics.map(async (topic) => [topic, await admin.fetchTopicOffsets(topic)]))
        )

        const { groups } = await admin.listGroups()
        const consumerGroupOffsets = await Promise.all(
            groups.map(async ({ groupId }) => [groupId, await admin.fetchOffsets({ groupId })] as const)
        )

        for (const [groupId, offsets] of consumerGroupOffsets) {
            for (const { topic, partitions } of offsets) {
                for (const { partition, offset } of partitions) {
                    console.debug(
                        `Checking ${groupId} ${topic} ${partition} ${offset} ${topicOffsets[topic][partition].offset}`
                    )
                    assert(
                        topicOffsets[topic][partition].offset === offset,
                        `Consumer group ${groupId} has lag on ${topic}[${partition}]: ${{
                            lastOffset: topicOffsets[topic][partition].offset,
                            consumerOffset: offset,
                        }}`
                    )
                }
            }
        }
    } catch (error) {
        throw error
    } finally {
        await admin.disconnect()
    }
}
