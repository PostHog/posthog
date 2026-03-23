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
    const promises: Promise<{ outputName: O; config: IngestionOutputConfig }>[] = []

    for (const outputName in definitions) {
        const definition = definitions[outputName]
        const envKey = outputName.toUpperCase()
        const producerNameOverride = process.env[`INGESTION_OUTPUT_${envKey}_PRODUCER`]
        const producerName = producerNameOverride ?? definition.defaultProducerName

        // getProducer throws if the producer is not found, so all keys of O
        // are guaranteed to be present in the result or the call fails.
        promises.push(
            registry.getProducer(producerName).then((producer) => ({
                outputName,
                config: { topic: definition.topic, producer },
            }))
        )
    }

    const results = await Promise.all(promises)
    const resolved: Record<string, IngestionOutputConfig> = {}
    for (const { outputName, config } of results) {
        resolved[outputName] = config
    }

    // Safe cast: every key in Record<O, ...> has been resolved above.
    return new IngestionOutputs<O>(resolved as Record<O, IngestionOutputConfig>)
}
