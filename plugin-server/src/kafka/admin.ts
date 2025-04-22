import { AdminClient, CODES, GlobalConfig, LibrdKafkaError } from 'node-rdkafka'

import { isDevEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'

export const ensureTopicExists = async (connectionConfig: GlobalConfig, topic: string) => {
    // Ensures that a topic exists. If it doesn't, it will be created. If it
    // does, this is a no-op. We use -1 for the number of partitions and
    // replication factor as this will use the default values configured in
    // the Kafka broker config.

    const client = AdminClient.create(connectionConfig)
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
