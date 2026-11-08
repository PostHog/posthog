// This module has no imports so that the logger can use it. The Kafka config module
// imports defaultConfig, which throws at load time when Postgres env vars are missing.

// Every settable property that librdkafka flags `_RK_SENSITIVE` in rdkafka_conf.c, which
// librdkafka itself redacts in its debug output. Keep this in sync when librdkafka adds one.
// ssl.certificate.pem is not flagged there, but we have always kept it out of logs.
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

// Catches sensitive properties that a future librdkafka adds before the list above learns them.
const SENSITIVE_KAFKA_KEY_PATTERN = /password|passphrase|secret|\.pem$/

export function isSensitiveKafkaKey(key: string): boolean {
    return SENSITIVE_KAFKA_KEYS.has(key) || SENSITIVE_KAFKA_KEY_PATTERN.test(key)
}
