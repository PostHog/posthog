import { AdminClient, CODES, GlobalConfig, IAdminClient, LibrdKafkaError } from 'node-rdkafka'

import { status } from '../utils/status'

export const ensureTopicExists = async (adminClient: IAdminClient, topic: string, timeout: number) => {
    // Ensures that a topic exists. If it doesn't, it will be created. If it
    // does, this is a no-op. We use -1 for the number of partitions and
    // replication factor as this will use the default values configured in
    // the Kafka broker config.
    return await new Promise((resolve, reject) =>
        adminClient.createTopic(
            { topic, num_partitions: -1, replication_factor: -1 },
            timeout,
            (error: LibrdKafkaError) => {
                if (error) {
                    if (error.code === CODES.ERRORS.ERR_TOPIC_ALREADY_EXISTS) {
                        // If it's a topic already exists error, then we don't need
                        // to error.
                        resolve(adminClient)
                    } else {
                        status.error('🔥', 'Failed to create topic', { topic, error })
                        reject(error)
                    }
                } else {
                    status.info('🔁', 'Created topic', { topic })
                    resolve(adminClient)
                }
            }
        )
    )
}

export const createAdminClient = (connectionConfig: GlobalConfig) => {
    return AdminClient.create(connectionConfig)
}
