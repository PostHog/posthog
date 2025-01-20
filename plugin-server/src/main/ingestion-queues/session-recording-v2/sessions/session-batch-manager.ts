import { PromiseQueue } from './promise-queue'
import { SessionBatchRecorder } from './session-batch-recorder'

export interface SessionBatchManagerConfig {
    maxBatchSizeBytes: number
}

export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private queue: PromiseQueue<void>
    private readonly maxBatchSizeBytes: number

    constructor(config: SessionBatchManagerConfig) {
        this.currentBatch = new SessionBatchRecorder()
        this.queue = new PromiseQueue()
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
    }

    public async withBatch(callback: (batch: SessionBatchRecorder) => Promise<void>): Promise<void> {
        return this.queue.add(() => callback(this.currentBatch))
    }

    public async flush(): Promise<void> {
        return this.queue.add(async () => {
            // TODO: Process the last batch, for now we just throw it away
            this.currentBatch = new SessionBatchRecorder()
            return Promise.resolve()
        })
    }

    public async flushIfFull(): Promise<void> {
        return this.queue.add(async () => {
            if (this.currentBatch.size >= this.maxBatchSizeBytes) {
                // TODO: Process the last batch, for now we just throw it away
                this.currentBatch = new SessionBatchRecorder()
            }
            return Promise.resolve()
        })
    }
}
