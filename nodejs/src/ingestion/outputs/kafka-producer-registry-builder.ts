import { ProducerGlobalConfig } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { AllowedConfigKey, parseProducerConfig } from './kafka-producer-config'
import { KafkaProducerRegistry } from './kafka-producer-registry'

const SENSITIVE_KEYS = new Set([
    'sasl.password',
    'sasl.oauthbearer.client.secret',
    'ssl.key.password',
    'ssl.key.pem',
    'ssl.certificate.pem',
])

function redactConfig(config: ProducerGlobalConfig): Record<string, unknown> {
    return Object.fromEntries(Object.entries(config).map(([k, v]) => [k, SENSITIVE_KEYS.has(k) ? '***' : v]))
}

/**
 * Builder for `KafkaProducerRegistry` that validates config keys at compile time.
 *
 * Each `register()` call adds a named producer and accumulates its config key requirements
 * in the `CK` type parameter. `build(config)` then checks that the config object contains
 * all accumulated keys.
 *
 * @example
 * ```ts
 * const registry = await new KafkaProducerRegistryBuilder(config.KAFKA_CLIENT_RACK)
 *     .register('DEFAULT', DEFAULT_PRODUCER_CONFIG_MAP)
 *     .build(config)
 * // registry is KafkaProducerRegistry<'DEFAULT'>
 * ```
 */
export class KafkaProducerRegistryBuilder<P extends string = never, CK extends string = never> {
    private registrations = new Map<string, Partial<Record<AllowedConfigKey, CK>>>()

    constructor(private kafkaClientRack: string | undefined) {}

    /**
     * Register a producer with a name and rdkafka-to-config-key mapping.
     *
     * The config key names are accumulated in the `CK` type parameter and checked
     * against the config object when `build()` is called.
     */
    register<Name extends string, ConfigKeys extends string>(
        name: Name,
        configMap: Partial<Record<AllowedConfigKey, ConfigKeys>>
    ): KafkaProducerRegistryBuilder<P | Name, CK | ConfigKeys> {
        const next = new KafkaProducerRegistryBuilder<P | Name, CK | ConfigKeys>(this.kafkaClientRack)
        next.registrations = new Map(this.registrations)
        next.registrations.set(name, configMap)
        return next
    }

    /**
     * Create all registered producers and return an immutable registry.
     *
     * The compiler verifies that the config contains all accumulated config keys.
     * Connects to brokers in parallel. Throws if any producer fails to connect.
     */
    async build(config: Record<CK, string>): Promise<KafkaProducerRegistry<P>> {
        const producers: Record<string, KafkaProducerWrapper> = {}

        await Promise.all(
            Array.from(this.registrations.entries()).map(async ([name, configMap]) => {
                const values: Record<string, string> = {}
                for (const [rdkafkaKey, configKey] of Object.entries(configMap)) {
                    if (configKey !== undefined) {
                        const value = config[configKey]
                        if (value) {
                            values[rdkafkaKey] = value
                        }
                    }
                }

                const resolvedConfig = parseProducerConfig(values)
                logger.info('📝', `Creating producer "${name}"`, { config: redactConfig(resolvedConfig) })
                producers[name] = await KafkaProducerWrapper.createWithConfig(
                    this.kafkaClientRack,
                    resolvedConfig,
                    name
                )
            })
        )

        // TypeScript cannot verify that an imperatively-built Record has all keys of a
        // generic union P. The builder guarantees this: every `register()` call adds an
        // entry to `this.registrations`, and `build()` creates a producer for each entry.
        return new KafkaProducerRegistry<P>(producers as Record<P, KafkaProducerWrapper>)
    }
}
