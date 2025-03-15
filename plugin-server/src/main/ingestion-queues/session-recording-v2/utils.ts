import { KafkaConsumer, PartitionMetadata } from 'node-rdkafka'

import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'

export const getPartitionsForTopic = (
    kafkaConsumer: KafkaConsumer | undefined,
    topic: string
): Promise<PartitionMetadata[]> => {
    return new Promise<PartitionMetadata[]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }
        kafkaConsumer.getMetadata({ topic }, (err, meta) => {
            if (err) {
                captureException(err)
                logger.error('🔥', 'Failed to get partition metadata', err)
                return reject(err)
            }

            return resolve(meta.topics.find((x) => x.name === topic)?.partitions ?? [])
        })
    })
}
