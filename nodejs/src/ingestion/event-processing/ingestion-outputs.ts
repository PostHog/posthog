import { MessageValue } from 'node-rdkafka'

import { KafkaProducerWrapper, MessageKey, MessageWithoutTopic } from '../../kafka/producer'
import { logger } from '../../utils/logger'

export * from './output-types'

export interface IngestionOutputConfig {
    topic: string
    producer: KafkaProducerWrapper
}

export class IngestionOutputs<O extends string> {
    constructor(private outputs: Record<O, IngestionOutputConfig>) {}

    /** Produce a single message to the given output. */
    async produce(
        output: O,
        message: { value: MessageValue; key: MessageKey; headers?: Record<string, string> }
    ): Promise<void> {
        const { topic, producer } = this.outputs[output]
        return producer.produce({ topic, ...message })
    }

    /** Queue one or more messages to the given output (parallel, no ordering guarantee). */
    async queueMessages(output: O, messages: MessageWithoutTopic[]): Promise<void> {
        const { topic, producer } = this.outputs[output]
        return producer.queueMessages({ topic, messages })
    }

    /**
     * Check that all unique producers can reach their brokers.
     * Returns the output names of any that fail.
     */
    async checkHealth(timeoutMs = 5000): Promise<string[]> {
        const failures: string[] = []
        const checked = new Set<KafkaProducerWrapper>()

        for (const outputName in this.outputs) {
            const { producer } = this.outputs[outputName]
            if (checked.has(producer)) {
                continue
            }
            checked.add(producer)

            try {
                await producer.checkConnection(timeoutMs)
            } catch (error) {
                logger.error('🔴', `Producer health check failed for output "${outputName}"`, { error })
                failures.push(outputName)
            }
        }

        return failures
    }

    /**
     * Check that all non-empty topics exist on their brokers.
     * Returns the output names of any that fail.
     */
    async checkTopics(timeoutMs = 10000): Promise<string[]> {
        const failures: string[] = []
        const checked = new Map<KafkaProducerWrapper, Set<string>>()

        for (const outputName in this.outputs) {
            const { topic, producer } = this.outputs[outputName]
            if (!topic) {
                continue
            }

            const producerChecked = checked.get(producer) ?? new Set()
            if (producerChecked.has(topic)) {
                continue
            }
            producerChecked.add(topic)
            checked.set(producer, producerChecked)

            try {
                await producer.checkTopicExists(topic, timeoutMs)
            } catch (error) {
                logger.error('🔴', `Topic check failed for output "${outputName}" topic "${topic}"`, { error })
                failures.push(outputName)
            }
        }

        return failures
    }
}
