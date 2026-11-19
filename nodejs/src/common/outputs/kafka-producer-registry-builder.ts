import { BlackholeKafkaProducer } from '~/common/kafka/blackhole-producer'
import { redactKafkaConfig } from '~/common/kafka/config'
import { LazyKafkaProducer } from '~/common/kafka/lazy-producer'
import { KafkaProducer, KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'

import { AllowedConfigKey, parseProducerConfig } from './kafka-producer-config'
import { KafkaProducerRegistry } from './kafka-producer-registry'

const LAZY_CONNECT_WAIT_MS = 5_000

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
 *     .register('INGESTION_UPSTREAM', INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP)
 *     .build(config)
 * // registry is KafkaProducerRegistry<'INGESTION_UPSTREAM'>
 * ```
 */
export class KafkaProducerRegistryBuilder<P extends string = never, CK extends string = never> {
    private registrations = new Map<string, Partial<Record<AllowedConfigKey, CK>>>()
    private blackholes = new Set<string>()
    private lazy = new Set<string>()

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
        next.blackholes = new Set(this.blackholes)
        next.lazy = new Set(this.lazy)
        next.registrations.set(name, configMap)
        return next
    }

    /** Like `register()`, but the producer connects in the background: `build()` waits for it briefly and never fails on it. */
    registerLazy<Name extends string, ConfigKeys extends string>(
        name: Name,
        configMap: Partial<Record<AllowedConfigKey, ConfigKeys>>
    ): KafkaProducerRegistryBuilder<P | Name, CK | ConfigKeys> {
        const next = this.register(name, configMap)
        next.lazy.add(name)
        return next
    }

    registerBlackhole<Name extends string>(name: Name): KafkaProducerRegistryBuilder<P | Name, CK> {
        const next = new KafkaProducerRegistryBuilder<P | Name, CK>(this.kafkaClientRack)
        next.registrations = new Map(this.registrations)
        next.blackholes = new Set(this.blackholes)
        next.lazy = new Set(this.lazy)
        next.blackholes.add(name)
        return next
    }

    /**
     * Create all registered producers and return an immutable registry.
     *
     * The compiler verifies that the config contains all accumulated config keys.
     * Connects to brokers in parallel. Throws if any producer fails to connect.
     */
    async build(config: Record<CK, string>): Promise<KafkaProducerRegistry<P>> {
        const producers: Record<string, KafkaProducer> = {}
        const lazies: LazyKafkaProducer[] = []
        for (const name of this.blackholes) {
            producers[name] = new BlackholeKafkaProducer(name)
        }

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
                logger.info('📝', `Creating producer "${name}"`, { config: redactKafkaConfig(resolvedConfig) })
                const connect = () => KafkaProducerWrapper.createWithConfig(this.kafkaClientRack, resolvedConfig, name)
                if (this.lazy.has(name)) {
                    const lazy = new LazyKafkaProducer(connect)
                    lazies.push(lazy)
                    // A healthy cluster is connected before the pod takes traffic; a down one delays boot by this much.
                    await lazy.waitConnected(LAZY_CONNECT_WAIT_MS)
                    producers[name] = lazy
                } else {
                    producers[name] = await connect()
                }
            })
        ).catch(async (error) => {
            // A failed build returns no registry to disconnect them, so their background retries would run on.
            await Promise.allSettled(lazies.map((lazy) => lazy.disconnect()))
            throw error
        })

        // TypeScript cannot verify that an imperatively-built Record has all keys of a
        // generic union P. The builder guarantees this: every `register()` and
        // `registerBlackhole()` call adds a name, and `build()` creates a producer for each.
        return new KafkaProducerRegistry<P>(producers as Record<P, KafkaProducer>)
    }

    buildBlackhole(): KafkaProducerRegistry<P> {
        const producers: Record<string, KafkaProducer> = {}
        for (const name of [...this.registrations.keys(), ...this.blackholes]) {
            logger.warn('⚠️', `Producer "${name}" is a blackhole and discards every message`)
            producers[name] = new BlackholeKafkaProducer(name)
        }
        return new KafkaProducerRegistry<P>(producers as Record<P, KafkaProducer>)
    }
}
