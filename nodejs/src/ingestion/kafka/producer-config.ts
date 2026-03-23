import { ProducerGlobalConfig } from 'node-rdkafka'
import { hostname } from 'os'
import { z } from 'zod'

/** Zod schema for producer config. Defaults are baked in. */
const producerConfigSchema = z.object({
    'metadata.broker.list': z.string().default('kafka:9092'),
    'security.protocol': z.enum(['plaintext', 'ssl', 'sasl_plaintext', 'sasl_ssl']).optional(),
    'sasl.mechanisms': z.string().optional(),
    'sasl.username': z.string().optional(),
    'sasl.password': z.string().optional(),
    'compression.codec': z.enum(['none', 'gzip', 'snappy', 'lz4', 'zstd']).default('snappy'),
    'linger.ms': z.coerce.number().default(20),
    'batch.size': z.coerce.number().default(8 * 1024 * 1024),
    'queue.buffering.max.messages': z.coerce.number().default(100_000),
    'enable.ssl.certificate.verification': z
        .enum(['true', 'false'])
        .transform((v) => v === 'true')
        .optional(),
    log_level: z.coerce.number().default(4),
    'enable.idempotence': z
        .enum(['true', 'false'])
        .transform((v) => v === 'true')
        .default('true'),
    'metadata.max.age.ms': z.coerce.number().default(30000),
    'retry.backoff.ms': z.coerce.number().default(500),
    'socket.timeout.ms': z.coerce.number().default(30000),
    'max.in.flight.requests.per.connection': z.coerce.number().default(5),
})

export type AllowedConfigKey = keyof z.input<typeof producerConfigSchema>

/**
 * Build rdkafka producer config from a map of env var names to config keys.
 * Reads env vars, parses through zod (with defaults), throws on invalid values.
 */
export function getProducerConfig(envVarMap: Record<string, AllowedConfigKey>): ProducerGlobalConfig {
    const envValues: Record<string, string> = {}
    for (const envVar in envVarMap) {
        const value = process.env[envVar]
        if (value) {
            envValues[envVarMap[envVar]] = value
        }
    }

    const parsed = producerConfigSchema.parse(envValues)

    return { 'client.id': hostname(), ...parsed }
}
