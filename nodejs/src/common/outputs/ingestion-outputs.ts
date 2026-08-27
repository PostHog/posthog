import { MessageKey } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'
import { delay } from '~/common/utils/utils'

import { IngestionOutput } from './ingestion-output'
import { IngestionOutputMessage } from './types'

/**
 * Immutable container of resolved ingestion outputs.
 *
 * Each output maps a typed name (e.g. `'events'`, `'heatmaps'`) to an `IngestionOutput`.
 * Pipeline steps use `produce()` and `queueMessages()` to send messages by output name —
 * they never access the underlying producer or topic directly.
 *
 * @see `IngestionOutputsBuilder` for constructing instances from config.
 */
export class IngestionOutputs<O extends string> {
    constructor(private outputs: Record<O, IngestionOutput>) {}

    async produce(output: O, message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        await this.outputs[output].produce(message)
    }

    async queueMessages(output: O, messages: IngestionOutputMessage[]): Promise<void> {
        await this.outputs[output].queueMessages(messages)
    }

    /**
     * Check that all producers can reach their brokers.
     *
     * @param timeoutMs - Timeout for each broker connectivity check.
     * @returns Output names whose producers failed the check.
     */
    async checkHealth(timeoutMs = 5000): Promise<string[]> {
        const failures: string[] = []
        for (const outputName in this.outputs) {
            try {
                await this.outputs[outputName].checkHealth(timeoutMs)
            } catch {
                failures.push(outputName)
            }
        }
        if (failures.length > 0) {
            logger.error('🔴', `Health check failed for outputs: ${failures.join(', ')}`)
        }
        return failures
    }

    /**
     * Check that all non-empty topics exist on their brokers.
     *
     * Retries the failing subset, because a topic can be briefly absent from broker
     * metadata while it still exists: during a controller failover or leader election,
     * or in the window just after another client created it. Only a topic that stays
     * absent across every attempt is treated as missing, which keeps the startup gate
     * fatal for a genuinely absent topic.
     *
     * @param timeoutMs - Timeout for each topic metadata check.
     * @param attempts - How many times to check before reporting failure.
     * @param retryDelayMs - Wait between attempts.
     * @returns Output names whose topics failed every attempt.
     */
    async checkTopics(timeoutMs = 10000, attempts = 3, retryDelayMs = 500): Promise<string[]> {
        let pending = Object.keys(this.outputs) as O[]

        for (let attempt = 1; ; attempt++) {
            const failures: O[] = []
            for (const outputName of pending) {
                try {
                    await this.outputs[outputName].checkTopicExists(timeoutMs)
                } catch {
                    failures.push(outputName)
                }
            }

            if (failures.length === 0) {
                return []
            }
            if (attempt >= attempts) {
                logger.error('🔴', `Topic check failed for outputs: ${failures.join(', ')}`)
                return failures
            }

            logger.warn(
                '🟡',
                `Topic check failed for outputs: ${failures.join(', ')}. Retrying (${attempt}/${attempts - 1}).`
            )
            pending = failures
            await delay(retryDelayMs)
        }
    }
}

/**
 * Scope owner for an `IngestionOutputs` derived from already-running
 * infrastructure (typically a shared Kafka producer registry). `start()`
 * resolves the outputs via the `build` callback and verifies that every
 * output's topic is reachable; `stop()` is a no-op because the producer
 * registry's own component owns the connection lifetimes.
 */
export class IngestionOutputsComponent<O extends string> {
    constructor(private readonly build: () => IngestionOutputs<O>) {}

    async start(): Promise<{ value: IngestionOutputs<O>; stop: () => Promise<void> }> {
        const outputs = this.build()
        const failures = await outputs.checkTopics()
        if (failures.length > 0) {
            throw new Error(`Output topic verification failed for: ${failures.join(', ')}`)
        }
        return { value: outputs, stop: () => Promise.resolve() }
    }
}
