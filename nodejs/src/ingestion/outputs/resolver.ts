import { IngestionOutput, IngestionOutputTarget, IngestionOutputs } from './ingestion-outputs'
import { KafkaProducerRegistry } from './kafka-producer-registry'

/**
 * Static definition of an ingestion output.
 *
 * Specifies the default topic and producer, plus env var names for overriding each at deploy time.
 *
 * Optionally specifies env var names for a secondary target (topic + producer on a different broker).
 * When the secondary topic env var is set at runtime, produces will fan out to both targets.
 */
export interface IngestionOutputDefinition<P extends string> {
    defaultTopic: string
    defaultProducerName: P
    /** Env var name to override the producer for this output. */
    producerOverrideEnvVar: string
    /** Env var name to override the topic for this output. */
    topicOverrideEnvVar: string
    /** Env var name for a secondary topic. When set, enables dual writes. */
    secondaryTopicEnvVar?: string
    /** Env var name for the secondary producer. Required when secondaryTopicEnvVar is set. */
    secondaryProducerEnvVar?: string
}

/**
 * One-time factory that builds an `IngestionOutputs` from static definitions and a producer registry.
 *
 * For each output, resolves the producer (with env var override) and topic (with env var override).
 * All producers are resolved in parallel. Throws if any producer creation fails.
 *
 * @param registry - The producer registry to resolve producers from.
 * @param definitions - Static output definitions keyed by output name.
 * @returns A fully resolved `IngestionOutputs` instance ready for use by pipeline steps.
 */
export async function resolveIngestionOutputs<O extends string, P extends string>(
    registry: KafkaProducerRegistry<P>,
    definitions: Record<O, IngestionOutputDefinition<P>>
): Promise<IngestionOutputs<O>> {
    const promises: Promise<{ outputName: O; targets: IngestionOutputTarget[] }>[] = []

    for (const outputName in definitions) {
        const definition = definitions[outputName]
        const producerName = (process.env[definition.producerOverrideEnvVar] ?? definition.defaultProducerName) as P
        const topic = process.env[definition.topicOverrideEnvVar] ?? definition.defaultTopic

        const secondaryTopic = definition.secondaryTopicEnvVar
            ? process.env[definition.secondaryTopicEnvVar]
            : undefined
        const secondaryProducerName = definition.secondaryProducerEnvVar
            ? (process.env[definition.secondaryProducerEnvVar] as P | undefined)
            : undefined

        // getProducer throws if the producer is not found, so all keys of O
        // are guaranteed to be present in the result or the call fails.
        const primaryPromise = registry.getProducer(producerName)
        const secondaryPromise =
            secondaryTopic && secondaryProducerName ? registry.getProducer(secondaryProducerName) : undefined

        promises.push(
            Promise.all([primaryPromise, secondaryPromise ?? Promise.resolve(undefined)]).then(
                ([primaryProducer, secondaryProducer]) => {
                    const targets: IngestionOutputTarget[] = [{ topic, producer: primaryProducer, producerName }]
                    if (secondaryTopic && secondaryProducerName && secondaryProducer) {
                        targets.push({
                            topic: secondaryTopic,
                            producer: secondaryProducer,
                            producerName: secondaryProducerName,
                        })
                    }
                    return { outputName, targets }
                }
            )
        )
    }

    const results = await Promise.all(promises)
    const resolved: Record<string, IngestionOutput> = {}
    for (const { outputName, targets } of results) {
        resolved[outputName] = targets
    }

    // Safe cast: every key in Record<O, ...> has been resolved above.
    return new IngestionOutputs<O>(resolved as Record<O, IngestionOutput>)
}
