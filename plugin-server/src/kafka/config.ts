import { GlobalConfig } from 'node-rdkafka'
import { hostname } from 'os'

import { defaultConfig } from '../config/config'
import { KafkaConfig } from '../utils/db/hub'

export const RDKAFKA_LOG_LEVEL_MAPPING = {
    NOTHING: 0,
    DEBUG: 7,
    INFO: 6,
    WARN: 4,
    ERROR: 3,
}

export const createRdConnectionConfigFromEnvVars = (
    kafkaConfig: KafkaConfig,
    target: 'producer' | 'consumer'
): GlobalConfig => {
    const kafkaHosts =
        target === 'producer' ? kafkaConfig.KAFKA_PRODUCER_HOSTS ?? kafkaConfig.KAFKA_HOSTS : kafkaConfig.KAFKA_HOSTS

    const kafkaSecurityProtocol =
        target === 'producer'
            ? kafkaConfig.KAFKA_PRODUCER_SECURITY_PROTOCOL ?? kafkaConfig.KAFKA_SECURITY_PROTOCOL
            : kafkaConfig.KAFKA_SECURITY_PROTOCOL

    const kafkaClientId =
        target === 'producer'
            ? kafkaConfig.KAFKA_PRODUCER_CLIENT_ID ?? kafkaConfig.KAFKA_CLIENT_ID
            : kafkaConfig.KAFKA_CLIENT_ID

    // We get the config from the environment variables. This method should
    // convert those vars into connection settings that node-rdkafka can use. We
    // also set the client.id to the hostname of the machine. This is useful for debugging.
    const config: GlobalConfig = {
        'client.id': kafkaClientId || hostname(),
        'metadata.broker.list': kafkaHosts,
        'security.protocol': kafkaSecurityProtocol
            ? (kafkaSecurityProtocol.toLowerCase() as GlobalConfig['security.protocol'])
            : 'plaintext',
        'sasl.mechanisms': kafkaConfig.KAFKA_SASL_MECHANISM,
        'sasl.username': kafkaConfig.KAFKA_SASL_USER,
        'sasl.password': kafkaConfig.KAFKA_SASL_PASSWORD,
        'enable.ssl.certificate.verification': false,
        'client.rack': kafkaConfig.KAFKA_CLIENT_RACK,
        log_level: RDKAFKA_LOG_LEVEL_MAPPING[kafkaConfig.KAFKAJS_LOG_LEVEL],
    }

    if (kafkaConfig.KAFKA_TRUSTED_CERT_B64) {
        config['ssl.ca.pem'] = Buffer.from(kafkaConfig.KAFKA_TRUSTED_CERT_B64, 'base64').toString()
    }

    if (kafkaConfig.KAFKA_CLIENT_CERT_B64) {
        config['ssl.key.pem'] = Buffer.from(kafkaConfig.KAFKA_CLIENT_CERT_B64, 'base64').toString()
    }

    if (kafkaConfig.KAFKA_CLIENT_CERT_KEY_B64) {
        config['ssl.certificate.pem'] = Buffer.from(kafkaConfig.KAFKA_CLIENT_CERT_KEY_B64, 'base64').toString()
    }

    return config
}

export const getProducerConfigFromEnv = (): GlobalConfig => {
    return Object.entries(process.env)
        .filter(([key]) => key.startsWith('KAFKA_PRODUCER_'))
        .reduce((acc, [key, value]) => {
            // If there is an explicit config value then we don't override it
            if (!value || key in defaultConfig) {
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

            const rdkafkaKey = key
                .replace(/^KAFKA_PRODUCER_/, '')
                .replace(/_/g, '.')
                .toLowerCase()
            acc[rdkafkaKey] = parsedValue
            return acc
        }, {} as Record<string, any>)
}
