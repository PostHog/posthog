import { Message } from 'node-rdkafka'

import { Component } from '@posthog/ingestion-common/scopes/index'
import { KafkaConsumerInterface, createKafkaConsumer } from '@posthog/node-common/kafka/consumer/index'
import { instrumentFn } from '@posthog/node-common/tracing/tracing-utils'

export { createKafkaConsumer } from '@posthog/node-common/kafka/consumer/index'
export type { KafkaConsumerInterface } from '@posthog/node-common/kafka/consumer/index'

/**
 * Owns a Kafka consumer's lifetime as a scope entry. Start creates the
 * consumer and connects it to the provided per-batch handler; stop
 * disconnects it. Failures during connect cause the surrounding scope
 * to roll back already-started entries.
 */
export class KafkaConsumerComponent implements Component<KafkaConsumerInterface> {
    constructor(
        private readonly groupId: string,
        private readonly topic: string,
        private readonly handler: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>
    ) {}

    async start(): Promise<{ value: KafkaConsumerInterface; stop: () => Promise<void> }> {
        const kafkaConsumer = createKafkaConsumer({ groupId: this.groupId, topic: this.topic })
        await kafkaConsumer.connect(
            async (messages: Message[]) =>
                await instrumentFn(
                    { key: 'commonIngestionConsumer.handleEachBatch', sendException: false },
                    async () => await this.handler(messages)
                )
        )
        return {
            value: kafkaConsumer,
            stop: () => kafkaConsumer.disconnect(),
        }
    }
}
