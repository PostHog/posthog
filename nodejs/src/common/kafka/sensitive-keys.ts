// No imports: the logger loads this, and the Kafka config module throws at load without Postgres env vars.

// librdkafka's _RK_SENSITIVE keys plus ssl.certificate.pem; keep in sync with rust/capture/src/producers.rs.
export const SENSITIVE_KAFKA_KEYS: ReadonlySet<string> = new Set([
    'sasl.username',
    'sasl.password',
    'sasl.oauthbearer.config',
    'sasl.oauthbearer.client.secret',
    'sasl.oauthbearer.assertion.private.key.file',
    'sasl.oauthbearer.assertion.private.key.passphrase',
    'sasl.oauthbearer.assertion.private.key.pem',
    'ssl.key.location',
    'ssl.key.password',
    'ssl.key.pem',
    'ssl.ca.pem',
    'ssl.keystore.password',
    'ssl.certificate.pem',
])

// Catches sensitive keys a newer librdkafka adds before the list above does.
const SENSITIVE_KAFKA_KEY_PATTERN = /password|passphrase|secret|\.pem$/

export function isSensitiveKafkaKey(key: string): boolean {
    return SENSITIVE_KAFKA_KEYS.has(key) || SENSITIVE_KAFKA_KEY_PATTERN.test(key)
}
