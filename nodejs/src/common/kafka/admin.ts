import { pickBy } from 'lodash'
import { AdminClient, CODES, GlobalConfig, LibrdKafkaError } from 'node-rdkafka'

import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'

export const ensureTopicExists = async (connectionConfig: GlobalConfig, topic: string) => {
    // Before subscribing, we need to ensure that the topic exists. We don't
    // currently have a way to manage topic creation elsewhere (we handle this
    // via terraform in production but this isn't applicable e.g. to hobby
    // deployments) so we use the Kafka admin client to do so. We don't use the
    // Kafka `enable.auto.create.topics` option as the behaviour of this doesn't
    // seem to be well documented and it seems to not function as expected in
    // our testing of it, we end up getting "Unknown topic or partition" errors
    // on consuming, possibly similar to
    // https://github.com/confluentinc/confluent-kafka-dotnet/issues/1366.

    const client = AdminClient.create(
        pickBy(
            {
                'client.id': connectionConfig['client.id'],
                'metadata.broker.list': connectionConfig['metadata.broker.list'],
                'security.protocol': connectionConfig['security.protocol'],
                'sasl.mechanisms': connectionConfig['sasl.mechanisms'],
                'sasl.username': connectionConfig['sasl.username'],
                'sasl.password': connectionConfig['sasl.password'],
                'enable.ssl.certificate.verification': connectionConfig['enable.ssl.certificate.verification'],
                'ssl.ca.location': connectionConfig['ssl.ca.location'],
                'ssl.ca.pem': connectionConfig['ssl.ca.pem'],
                'ssl.certificate.location': connectionConfig['ssl.certificate.location'],
                'ssl.key.location': connectionConfig['ssl.key.location'],
                'ssl.key.password': connectionConfig['ssl.key.password'],
                'ssl.endpoint.identification.algorithm': connectionConfig['ssl.endpoint.identification.algorithm'],
                'client.rack': connectionConfig['client.rack'],
            },
            (value) => value !== undefined
        )
    )
    const timeout = isDevEnv() ? 30_000 : 5_000
    await new Promise<void>((resolve, reject) =>
        client.createTopic({ topic, num_partitions: -1, replication_factor: -1 }, timeout, (error: LibrdKafkaError) => {
            if (error) {
                if (error.code === CODES.ERRORS.ERR_TOPIC_ALREADY_EXISTS) {
                    // If it's a topic already exists error, then we don't need
                    // to error.
                    resolve()
                } else {
                    logger.error('🔥', 'Failed to create topic', { topic, error })
                    reject(error)
                }
            } else {
                logger.info('🔁', 'Created topic', { topic })
                resolve()
            }
        })
    )
    client.disconnect()
}
