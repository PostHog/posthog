import { TopicPartitionOffset } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { PartitionOffset } from '~/ingestion/pipelines/sessionreplay/types'

type CommitOffsetsCallback = (offsets: TopicPartitionOffset[]) => Promise<void>

export class KafkaOffsetManager {
    private partitionOffsets: Map<number, number> = new Map()

    constructor(
        private readonly commitOffsets: CommitOffsetsCallback,
        private readonly topic: string
    ) {}

    public trackOffset({ partition, offset }: PartitionOffset): void {
        // We track the next offset to process. Never move a partition backwards: callers can arrive
        // out of order (a drop tracked before a lower recorded offset), and committing the lower one
        // would replay everything in between.
        const nextOffset = offset + 1
        const current = this.partitionOffsets.get(partition)
        if (current === undefined || nextOffset > current) {
            this.partitionOffsets.set(partition, nextOffset)
        }
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
