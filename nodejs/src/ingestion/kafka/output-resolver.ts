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
 * After resolving, verifies that each producer can reach its broker (always).
 * When INGESTION_OUTPUTS_VERIFY_TOPICS=true, also verifies that each
 * non-empty topic exists. Throws on failure — callers should await this
 * during startup so the process crashes before becoming healthy.
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

    // Verify each producer can reach its broker
    const checkedProducers = new Set<IngestionOutputConfig['producer']>()
    for (const outputName in resolved) {
        const config = resolved[outputName]
        if (checkedProducers.has(config.producer)) {
            continue
        }
        checkedProducers.add(config.producer)

        logger.info('🔍', `Verifying broker connectivity for output "${outputName}"`)
        await config.producer.checkConnection()
    }

    // Optionally verify all topics exist (skip empty topics like redirect)
    if (process.env.INGESTION_OUTPUTS_VERIFY_TOPICS === 'true') {
        const checkedTopics = new Map<IngestionOutputConfig['producer'], Set<string>>()
        for (const outputName in resolved) {
            const config = resolved[outputName]
            if (!config.topic) {
                continue
            }

            const producerChecked = checkedTopics.get(config.producer) ?? new Set()
            if (producerChecked.has(config.topic)) {
                continue
            }
            producerChecked.add(config.topic)
            checkedTopics.set(config.producer, producerChecked)

            logger.info('🔍', `Verifying output "${outputName}" topic "${config.topic}"`)
            await config.producer.checkTopicExists(config.topic)
        }
    }

    return new IngestionOutputs<O>(resolved)
}
