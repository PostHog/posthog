import { KafkaOffsetManager } from '../kafka/offset-manager'
import { PromiseQueue } from './promise-queue'
import { SessionBatchRecorder } from './session-batch-recorder'

export interface SessionBatchManagerConfig {
    maxBatchSizeBytes: number
    maxBatchAgeMs: number
    offsetManager: KafkaOffsetManager
}

export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private queue: PromiseQueue<void>
    private readonly maxBatchSizeBytes: number
    private readonly maxBatchAgeMs: number
    private readonly offsetManager: KafkaOffsetManager
    private lastFlushTime: number

    constructor(config: SessionBatchManagerConfig) {
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
        this.maxBatchAgeMs = config.maxBatchAgeMs
        this.offsetManager = config.offsetManager
        this.currentBatch = new SessionBatchRecorder(this.offsetManager)
        this.queue = new PromiseQueue()
        this.lastFlushTime = Date.now()
    }

    public async withBatch(callback: (batch: SessionBatchRecorder) => Promise<void>): Promise<void> {
        return this.queue.add(() => callback(this.currentBatch))
    }

    public async flush(): Promise<void> {
        return this.queue.add(async () => {
            await this.rotateBatch()
        })
    }

    public shouldFlush(): boolean {
        const batchSize = this.currentBatch.size
        const batchAge = Date.now() - this.lastFlushTime
        return batchSize >= this.maxBatchSizeBytes || batchAge >= this.maxBatchAgeMs
    }

    public async discardPartitions(partitions: number[]): Promise<void> {
        return this.queue.add(async () => {
            for (const partition of partitions) {
                this.currentBatch.discardPartition(partition)
            }
            return Promise.resolve()
        })
    }

    private async rotateBatch(): Promise<void> {
        await this.currentBatch.flush()
        this.currentBatch = new SessionBatchRecorder(this.offsetManager)
        this.lastFlushTime = Date.now()
    }
}
