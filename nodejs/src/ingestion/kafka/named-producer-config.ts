import { GlobalConfig } from 'node-rdkafka'

import { parseEnvToRdkafkaConfig } from '../../kafka/config'

/**
 * Read rdkafka config for a named producer from INGESTION_KAFKA_PRODUCER_{NAME}_* env vars.
 * Returns an empty object if no matching env vars exist.
 */
export function getNamedProducerConfig(name: string): GlobalConfig {
    const prefix = `INGESTION_KAFKA_PRODUCER_${name.toUpperCase()}_`
    return parseEnvToRdkafkaConfig(prefix)
}

/**
 * Returns true if any INGESTION_KAFKA_PRODUCER_{NAME}_* env vars exist.
 */
export function hasNamedProducerConfig(name: string): boolean {
    const prefix = `INGESTION_KAFKA_PRODUCER_${name.toUpperCase()}_`
    return Object.keys(process.env).some((key) => key.startsWith(prefix))
}
