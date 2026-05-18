import { MessageKey } from '../../kafka/producer'
import { logger } from '../../utils/logger'
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
     * Idempotently create all non-empty topics via the admin API. Each output's
     * admin call has its own 30s timeout in dev — run them in parallel so one
     * slow broker doesn't serialize startup across 10+ outputs. Failures are
     * logged, not thrown; callers re-run `checkTopics()` as the source of truth.
     */
    async ensureTopics(): Promise<string[]> {
        const results = await Promise.all(
            Object.keys(this.outputs).map(async (outputName) => {
                try {
                    await this.outputs[outputName as O].ensureTopicExists()
                    return null
                } catch (error) {
                    logger.error('🔴', `Topic creation failed for output "${outputName}"`, { error })
                    return outputName
                }
            })
        )
        return results.filter((name): name is string => name !== null)
    }

    /**
     * Check that all non-empty topics exist on their brokers.
     *
     * @param timeoutMs - Timeout for each topic metadata check.
     * @returns Output names whose topics failed the check.
     */
    async checkTopics(timeoutMs = 10000): Promise<string[]> {
        const failures: string[] = []
        for (const outputName in this.outputs) {
            try {
                await this.outputs[outputName].checkTopicExists(timeoutMs)
            } catch {
                failures.push(outputName)
            }
        }
        if (failures.length > 0) {
            logger.error('🔴', `Topic check failed for outputs: ${failures.join(', ')}`)
        }
        return failures
    }
}

/**
 * Startup gate shared by every server that owns an `IngestionOutputs`. When
 * auto-create is on (dev default), tries to create missing topics via the
 * admin API — broker metadata reads don't trigger broker-side auto-create, so
 * a fresh cluster would otherwise fail the verification step below. Then
 * verifies all topics exist and throws if any are still missing (the prod
 * safety net for misconfigured topic names).
 */
export async function ensureAndVerifyOutputTopics(
    outputs: IngestionOutputs<string>,
    autoCreateEnabled: boolean
): Promise<void> {
    if (autoCreateEnabled) {
        await outputs.ensureTopics()
    }
    const topicFailures = await outputs.checkTopics()
    if (topicFailures.length > 0) {
        throw new Error(`Output topic verification failed for: ${topicFailures.join(', ')}`)
    }
}
