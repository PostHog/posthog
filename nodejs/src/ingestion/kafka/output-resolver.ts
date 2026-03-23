import { IngestionOutputConfig, IngestionOutputs } from './ingestion-outputs'
import { KafkaProducerRegistry } from './producer-registry'

export interface IngestionOutputDefinition<P extends string> {
    defaultTopic: string
    defaultProducerName: P
    producerOverrideEnvVar: string
    topicOverrideEnvVar: string
}

/**
 * Resolve output definitions into an IngestionOutputs instance.
 *
 * For each output, reads the producer and topic override env vars (if set),
 * otherwise uses defaults from the definition.
 */
export async function resolveIngestionOutputs<O extends string, P extends string>(
    registry: KafkaProducerRegistry<P>,
    definitions: Record<O, IngestionOutputDefinition<P>>
): Promise<IngestionOutputs<O>> {
    const promises: Promise<{ outputName: O; config: IngestionOutputConfig }>[] = []

    for (const outputName in definitions) {
        const definition = definitions[outputName]
        const producerName = (process.env[definition.producerOverrideEnvVar] ?? definition.defaultProducerName) as P
        const topic = process.env[definition.topicOverrideEnvVar] ?? definition.defaultTopic

        // getProducer throws if the producer is not found, so all keys of O
        // are guaranteed to be present in the result or the call fails.
        promises.push(
            registry.getProducer(producerName).then((producer) => ({
                outputName,
                config: { topic, producer },
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
