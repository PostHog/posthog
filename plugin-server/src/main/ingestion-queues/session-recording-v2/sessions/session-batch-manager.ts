import { KafkaOffsetManager } from '../kafka/offset-manager'
import { PromiseQueue } from './promise-queue'
import { SessionBatchRecorder } from './session-batch-recorder'

export interface SessionBatchManagerConfig {
    maxBatchSizeBytes: number
    createBatch: () => SessionBatchRecorder
    offsetManager: KafkaOffsetManager
}

export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private queue: PromiseQueue<void>
    private readonly maxBatchSizeBytes: number
    private readonly createBatch: () => SessionBatchRecorder
    private readonly offsetManager: KafkaOffsetManager

    constructor(config: SessionBatchManagerConfig) {
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
        this.createBatch = config.createBatch
        this.offsetManager = config.offsetManager
        this.currentBatch = this.offsetManager.wrapBatch(this.createBatch())
        this.queue = new PromiseQueue()
    }

    public async withBatch(callback: (batch: SessionBatchRecorder) => Promise<void>): Promise<void> {
        return this.queue.add(() => callback(this.currentBatch))
    }

    public async flush(): Promise<void> {
        return this.queue.add(async () => {
            await this.rotateBatch()
        })
    }

    public async flushIfFull(): Promise<void> {
        return this.queue.add(async () => {
            if (this.currentBatch.size >= this.maxBatchSizeBytes) {
                await this.rotateBatch()
            }
        })
    }

    private async rotateBatch(): Promise<void> {
        await this.currentBatch.flush()
        await this.offsetManager.commit()
        this.currentBatch = this.offsetManager.wrapBatch(this.createBatch())
    }
}
