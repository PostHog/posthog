import { GlobalConfig } from 'node-rdkafka'
import { hostname } from 'os'

import { KafkaConfig } from '../utils/db/hub'
import { KafkaProducerConfig } from './producer'

export const RDKAFKA_LOG_LEVEL_MAPPING = {
    NOTHING: 0,
    DEBUG: 7,
    INFO: 6,
    WARN: 4,
    ERROR: 3,
}

export const createRdConnectionConfigFromEnvVars = (kafkaConfig: KafkaConfig): GlobalConfig => {
    // We get the config from the environment variables. This method should
    // convert those vars into connection settings that node-rdkafka can use. We
    // also set the client.id to the hostname of the machine. This is useful for debugging.
    const config: GlobalConfig = {
        'client.id': kafkaConfig.KAFKA_CLIENT_ID || hostname(),
        'metadata.broker.list': kafkaConfig.KAFKA_HOSTS,
        'security.protocol': kafkaConfig.KAFKA_SECURITY_PROTOCOL
            ? (kafkaConfig.KAFKA_SECURITY_PROTOCOL.toLowerCase() as GlobalConfig['security.protocol'])
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

export const createRdProducerConfigFromEnvVars = (producerConfig: KafkaProducerConfig): KafkaProducerConfig => {
    return {
        KAFKA_PRODUCER_LINGER_MS: producerConfig.KAFKA_PRODUCER_LINGER_MS,
        KAFKA_PRODUCER_BATCH_SIZE: producerConfig.KAFKA_PRODUCER_BATCH_SIZE,
        KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: producerConfig.KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES,
    }
}
