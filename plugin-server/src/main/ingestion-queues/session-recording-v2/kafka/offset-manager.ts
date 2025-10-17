import { TopicPartitionOffset } from 'node-rdkafka'

import { logger } from '../../../../utils/logger'
import { PartitionOffset } from '../types'

type CommitOffsetsCallback = (offsets: TopicPartitionOffset[]) => Promise<void>

export class KafkaOffsetManager {
    private partitionOffsets: Map<number, number> = new Map()

    constructor(
        private readonly commitOffsets: CommitOffsetsCallback,
        private readonly topic: string
    ) {}

    public trackOffset({ partition, offset }: PartitionOffset): void {
        // We track the next offset to process
        this.partitionOffsets.set(partition, offset + 1)
    }

    public discardPartition(partition: number): void {
        this.partitionOffsets.delete(partition)
    }

    public async commit(): Promise<void> {
        const topicPartitionOffsets: TopicPartitionOffset[] = []

        for (const [partition, offset] of this.partitionOffsets.entries()) {
            topicPartitionOffsets.push({
                topic: this.topic,
                partition,
                offset,
            })
        }

        if (topicPartitionOffsets.length > 0) {
            logger.info('🔁', 'offset_manager_committing_offsets', {
                topic: this.topic,
                offsets: topicPartitionOffsets.map(({ partition, offset }) => ({ partition, offset })),
            })
            await this.commitOffsets(topicPartitionOffsets)
            this.partitionOffsets.clear()
        }
    }
}
