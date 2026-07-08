import { ConsumerGlobalConfig, GlobalConfig } from 'node-rdkafka'

import { defaultConfig } from '../config/config'

export const RDKAFKA_LOG_LEVEL_MAPPING = {
    NOTHING: 0,
    DEBUG: 7,
    INFO: 6,
    WARN: 4,
    ERROR: 3,
}

export type KafkaConfigTarget =
    | 'PRODUCER'
    | 'CONSUMER'
    | 'CDP_PRODUCER'
    | 'WARPSTREAM_PRODUCER'
    | 'MONITORING_PRODUCER'
    | 'METRICS_PRODUCER'
    | 'WAREHOUSE_PRODUCER'

/**
 * Parse env vars with the given prefix into an rdkafka GlobalConfig.
 * Strips the prefix, converts underscores to dots, lowercases the key,
 * and coerces numeric/boolean values.
 *
 * @param skipKeysInDefaultConfig - when true, skips env vars whose key
 *   exists in defaultConfig (legacy behavior for KAFKA_* prefixed vars).
 */
export function parseEnvToRdkafkaConfig(
    prefix: string,
    options: { skipKeysInDefaultConfig?: boolean } = {}
): GlobalConfig {
    const { skipKeysInDefaultConfig = false } = options
    return Object.entries(process.env)
        .filter(([key]) => key.startsWith(prefix))
        .reduce(
            (acc, [key, value]) => {
                if (!value) {
                    return acc
                }
                if (skipKeysInDefaultConfig && key in defaultConfig) {
                    return acc
                }

                let parsedValue: string | number | boolean = value

                // parse value to a number if it is one
                const numberValue = Number(value)
                if (!isNaN(numberValue)) {
                    parsedValue = numberValue
                }

                // parse value to a boolean if it is one
                if (value.toLowerCase() === 'true') {
                    parsedValue = true
                } else if (value.toLowerCase() === 'false') {
                    parsedValue = false
                }

                const rdkafkaKey = key.replace(prefix, '').replace(/_/g, '.').toLowerCase()
                acc[rdkafkaKey] = parsedValue
                return acc
            },
            {} as Record<string, any>
        )
}

export const getKafkaConfigFromEnv = (target: KafkaConfigTarget): GlobalConfig => {
    // NOTE: We have learnt that having as much exposed config to the env as possible is really useful
    // That said we also want to be able to add defaults on the global config object
    // So what we do is we first find all values from the default config object and then in addition we add the env ones.
    return parseEnvToRdkafkaConfig(`KAFKA_${target}_`, { skipKeysInDefaultConfig: true })
}

/**
 * With the KIP-848 protocol (`group.protocol=consumer`, e.g. via
 * KAFKA_CONSUMER_GROUP_PROTOCOL=consumer) group session and assignment
 * settings are broker-side: librdkafka rejects the whole config at startup if
 * any classic-only key is explicitly set. Strip them after merging so the
 * hardcoded classic defaults don't break consumers opted into the new
 * protocol. Use `group.remote.assignor` instead of
 * `partition.assignment.strategy` to pick the server-side assignor.
 */
export function stripClassicProtocolConfig(config: ConsumerGlobalConfig): ConsumerGlobalConfig {
    if (config['group.protocol'] !== 'consumer') {
        return config
    }
    const stripped = { ...config }
    delete stripped['session.timeout.ms']
    delete stripped['heartbeat.interval.ms']
    delete stripped['partition.assignment.strategy']
    delete stripped['group.protocol.type']
    return stripped
}
