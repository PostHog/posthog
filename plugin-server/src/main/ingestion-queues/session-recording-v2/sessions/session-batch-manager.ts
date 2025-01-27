import { KafkaOffsetManager } from '../kafka/offset-manager'
import { SessionBatchRecorder } from './session-batch-recorder'

export interface SessionBatchManagerConfig {
    maxBatchSizeBytes: number
    maxBatchAgeMs: number
    offsetManager: KafkaOffsetManager
}

export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private readonly maxBatchSizeBytes: number
    private readonly maxBatchAgeMs: number
    private readonly offsetManager: KafkaOffsetManager
    private lastFlushTime: number

    constructor(config: SessionBatchManagerConfig) {
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
        this.maxBatchAgeMs = config.maxBatchAgeMs
        this.offsetManager = config.offsetManager
        this.currentBatch = new SessionBatchRecorder(this.offsetManager)
        this.lastFlushTime = Date.now()
    }

    public getCurrentBatch(): SessionBatchRecorder {
        return this.currentBatch
    }

    public async flush(): Promise<void> {
        await this.currentBatch.flush()
        this.currentBatch = new SessionBatchRecorder(this.offsetManager)
        this.lastFlushTime = Date.now()
    }

    public shouldFlush(): boolean {
        const batchSize = this.currentBatch.size
        const batchAge = Date.now() - this.lastFlushTime
        return batchSize >= this.maxBatchSizeBytes || batchAge >= this.maxBatchAgeMs
    }

    public discardPartitions(partitions: number[]): void {
        for (const partition of partitions) {
            this.currentBatch.discardPartition(partition)
        }
    }
}
