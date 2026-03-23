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
    async produce(output: O, message: Omit<MessageWithoutTopic, 'key'> & { key: MessageKey }): Promise<void> {
        const { topic, producer } = this.outputs[output]
        const value = typeof message.value === 'string' ? Buffer.from(message.value) : message.value
        return producer.produce({ ...message, topic, value })
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
        const checks = new Map<KafkaProducerWrapper, { outputName: string; promise: Promise<void> }>()

        for (const outputName in this.outputs) {
            const { producer } = this.outputs[outputName]
            if (!checks.has(producer)) {
                checks.set(producer, { outputName, promise: producer.checkConnection(timeoutMs) })
            }
        }

        const failures: string[] = []
        for (const [, { outputName, promise }] of checks) {
            try {
                await promise
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
        const checks: { outputName: string; topic: string; promise: Promise<void> }[] = []
        const seen = new Map<KafkaProducerWrapper, Set<string>>()

        for (const outputName in this.outputs) {
            const { topic, producer } = this.outputs[outputName]
            if (!topic) {
                continue
            }

            const producerSeen = seen.get(producer) ?? new Set()
            if (producerSeen.has(topic)) {
                continue
            }
            producerSeen.add(topic)
            seen.set(producer, producerSeen)

            checks.push({ outputName, topic, promise: producer.checkTopicExists(topic, timeoutMs) })
        }

        const failures: string[] = []
        for (const { outputName, topic, promise } of checks) {
            try {
                await promise
            } catch (error) {
                logger.error('🔴', `Topic check failed for output "${outputName}" topic "${topic}"`, { error })
                failures.push(outputName)
            }
        }

        return failures
    }
}
