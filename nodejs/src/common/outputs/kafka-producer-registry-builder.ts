import { ProducerGlobalConfig } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'

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

export class KafkaProducerRegistryBuilder<P extends string = never, CK extends string = never> {
    private registrations = new Map<string, Partial<Record<AllowedConfigKey, CK>>>()

    constructor(private kafkaClientRack: string | undefined) {}

    register<Name extends string, ConfigKeys extends string>(
        name: Name,
        configMap: Partial<Record<AllowedConfigKey, ConfigKeys>>
    ): KafkaProducerRegistryBuilder<P | Name, CK | ConfigKeys> {
        const next = new KafkaProducerRegistryBuilder<P | Name, CK | ConfigKeys>(this.kafkaClientRack)
        next.registrations = new Map(this.registrations)
        next.registrations.set(name, configMap)
        return next
    }

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
