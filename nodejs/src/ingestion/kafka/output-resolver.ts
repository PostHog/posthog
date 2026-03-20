import { logger } from '../../utils/logger'
import { IngestionOutputConfig, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { KafkaProducerRegistry } from './producer-registry'

export interface OutputDefinition {
    topic: string
    /** Producer name, or undefined to use the default producer. */
    defaultProducerName?: string
}

/**
 * Resolve output definitions into an IngestionOutputs instance.
 *
 * For each output, checks for an env var override:
 *   INGESTION_OUTPUT_{NAME}_PRODUCER — override the producer name
 *
 * Falls back to defaultProducerName from the definition (undefined = default producer).
 *
 * After resolving, verifies that each producer can reach its broker
 * and that each non-empty topic exists. Throws on failure.
 */
export async function resolveOutputs<O extends string>(
    registry: KafkaProducerRegistry,
    definitions: Record<O, OutputDefinition>
): Promise<IngestionOutputs<O>> {
    const resolved = {} as Record<O, IngestionOutputConfig>

    for (const outputName in definitions) {
        const definition = definitions[outputName]
        const envKey = outputName.toUpperCase()
        const producerNameOverride = process.env[`INGESTION_OUTPUT_${envKey}_PRODUCER`]
        const producerName = producerNameOverride ?? definition.defaultProducerName

        const producer = await registry.getProducer(producerName)
        resolved[outputName] = { topic: definition.topic, producer }
    }

    // Verify all topics exist (skip empty topics like redirect)
    const checked = new Map<IngestionOutputConfig['producer'], Set<string>>()
    for (const outputName in resolved) {
        const config = resolved[outputName]
        if (!config.topic) {
            continue
        }

        // Avoid checking the same producer+topic combination twice
        const producerChecked = checked.get(config.producer) ?? new Set()
        if (producerChecked.has(config.topic)) {
            continue
        }
        producerChecked.add(config.topic)
        checked.set(config.producer, producerChecked)

        logger.info('🔍', `Verifying output "${outputName}" topic "${config.topic}"`)
        await config.producer.checkTopicExists(config.topic)
    }

    return new IngestionOutputs<O>(resolved)
}
