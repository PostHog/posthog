import { KafkaProducerWrapper, MessageKey } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import {
    ingestionOutputsBatchSize,
    ingestionOutputsErrors,
    ingestionOutputsLatency,
    ingestionOutputsMessageValueBytes,
} from './metrics'
import { IngestionOutputMessage } from './types'

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
    async produce(output: O, message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        const { topic, producer } = this.outputs[output]
        ingestionOutputsMessageValueBytes.observe({ output }, message.value?.length ?? 0)
        ingestionOutputsBatchSize.observe({ output, method: 'produce' }, 1)
        return this.withMetrics(output, 'produce', () => producer.produce({ ...message, topic }))
    }

    /**
     * Queue one or more messages to the given output.
     *
     * Messages are produced in parallel with no ordering guarantee.
     *
     * @param output - The output name to produce to.
     * @param messages - The messages to produce.
     */
    async queueMessages(output: O, messages: IngestionOutputMessage[]): Promise<void> {
        const { topic, producer } = this.outputs[output]
        for (const m of messages) {
            ingestionOutputsMessageValueBytes.observe({ output }, m.value?.length ?? 0)
        }
        ingestionOutputsBatchSize.observe({ output, method: 'queueMessages' }, messages.length)
        return this.withMetrics(output, 'queueMessages', () => producer.queueMessages({ topic, messages }))
    }

    private async withMetrics<T>(output: O, method: string, fn: () => Promise<T>): Promise<T> {
        const end = ingestionOutputsLatency.startTimer({ output, method })
        try {
            return await fn()
        } catch (error) {
            ingestionOutputsErrors.inc({ output, method })
            throw error
        } finally {
            end()
        }
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
