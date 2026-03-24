import { KafkaProducerWrapper, MessageKey, MessageWithoutTopic } from '../../kafka/producer'
import { logger } from '../../utils/logger'

/** A resolved output: the Kafka topic and the producer to write to it. */
export interface IngestionOutput {
    topic: string
    producer: KafkaProducerWrapper
}

/**
 * Immutable container of resolved ingestion outputs.
 *
 * Each output maps a typed name (e.g. `'events'`, `'heatmaps'`) to a specific Kafka topic and producer.
 * Pipeline steps use `produce()` and `queueMessages()` to send messages by output name —
 * they never access the underlying producer or topic directly.
 *
 * @see `resolveIngestionOutputs()` for building an instance from output definitions.
 */
export class IngestionOutputs<O extends string> {
    constructor(private outputs: Record<O, IngestionOutput>) {}

    /**
     * Produce a single message to the given output.
     *
     * @param output - The output name to produce to.
     * @param message - The message to produce. Key is required for partitioning.
     */
    async produce(output: O, message: Omit<MessageWithoutTopic, 'key'> & { key: MessageKey }): Promise<void> {
        const { topic, producer } = this.outputs[output]
        const value = typeof message.value === 'string' ? Buffer.from(message.value) : message.value
        return producer.produce({ ...message, topic, value })
    }

    /**
     * Queue one or more messages to the given output.
     *
     * Messages are produced in parallel with no ordering guarantee.
     *
     * @param output - The output name to produce to.
     * @param messages - The messages to produce.
     */
    async queueMessages(output: O, messages: MessageWithoutTopic[]): Promise<void> {
        const { topic, producer } = this.outputs[output]
        return producer.queueMessages({ topic, messages })
    }

    /**
     * Check that all unique producers can reach their brokers.
     *
     * Checks are run in parallel, one per unique producer. Deduplicates when multiple outputs share a producer.
     *
     * @param timeoutMs - Timeout for each broker connectivity check.
     * @returns Output names whose producers failed the check.
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
     *
     * Checks are run in parallel. Deduplicates same topic on same producer. Skips outputs with empty topics.
     *
     * @param timeoutMs - Timeout for each topic metadata check.
     * @returns Output names whose topics failed the check.
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
