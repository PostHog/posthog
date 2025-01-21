import { TopicPartitionOffset } from 'node-rdkafka'

import { SessionBatchRecorder } from '../sessions/session-batch-recorder'
import { MessageWithTeam } from '../teams/types'

interface PartitionOffset {
    partition: number
    offset: number
}

type CommitOffsetsCallback = (offsets: TopicPartitionOffset[]) => Promise<void>

class OffsetTrackingSessionBatchRecorder implements SessionBatchRecorder {
    constructor(private readonly recorder: SessionBatchRecorder, private readonly offsetManager: KafkaOffsetManager) {}

    public record(message: MessageWithTeam): number {
        const bytesWritten = this.recorder.record(message)
        this.offsetManager.trackOffset(message.message.metadata)
        return bytesWritten
    }

    public async flush(): Promise<void> {
        await this.recorder.flush()
    }

    public get size(): number {
        return this.recorder.size
    }
}

export class KafkaOffsetManager {
    private partitionOffsets: Map<number, number> = new Map()

    constructor(private readonly commitOffsets: CommitOffsetsCallback, private readonly topic: string) {}

    public wrapBatch(recorder: SessionBatchRecorder): SessionBatchRecorder {
        return new OffsetTrackingSessionBatchRecorder(recorder, this)
    }

    public trackOffset({ partition, offset }: PartitionOffset): void {
        // We track the next offset to process
        this.partitionOffsets.set(partition, offset + 1)
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
            await this.commitOffsets(topicPartitionOffsets)
            this.partitionOffsets.clear()
        }
    }
}
