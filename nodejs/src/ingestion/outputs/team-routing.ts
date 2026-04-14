import { IngestionOutputs } from './ingestion-outputs'
import { KafkaProducerRegistry } from './kafka-producer-registry'
import { SingleIngestionOutput } from './single-ingestion-output'
import { TeamRoutedIngestionOutput } from './team-routed-ingestion-output'

/**
 * Parse a comma-separated string of team IDs into a Set.
 * Empty or whitespace-only strings return an empty set.
 */
export function parseTeamIds(raw: string): Set<number> {
    if (!raw.trim()) {
        return new Set()
    }
    return new Set(
        raw
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => !isNaN(n))
    )
}

/**
 * Wrap each output in a `TeamRoutedIngestionOutput` so messages for the
 * specified teams are produced via a different producer.
 *
 * The topic stays the same — only the producer (broker connection) changes.
 * If `teamIds` is empty the outputs are returned unchanged.
 */
export function applyTeamRouting<O extends string>(
    outputs: IngestionOutputs<O>,
    producerRegistry: KafkaProducerRegistry<string>,
    teamIds: Set<number>,
    producerName: string,
    config: Record<string, string>
): IngestionOutputs<O> {
    if (teamIds.size === 0) {
        return outputs
    }

    const teamProducer = producerRegistry.getProducer(producerName)

    return outputs.wrapOutputs((name, defaultOutput) => {
        // Look up the topic for this output from config.
        // Convention: INGESTION_OUTPUT_<NAME>_TOPIC
        const topicKey = `INGESTION_OUTPUT_${name.toUpperCase()}_TOPIC`
        const topic = config[topicKey]

        if (!topic) {
            // Output has no known topic config (shouldn't happen) — skip routing
            return defaultOutput
        }

        const teamOutput = new SingleIngestionOutput(name, topic, teamProducer, producerName)
        return new TeamRoutedIngestionOutput(defaultOutput, teamOutput, teamIds)
    })
}
