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

    return new IngestionOutputs<O>(resolved)
}
