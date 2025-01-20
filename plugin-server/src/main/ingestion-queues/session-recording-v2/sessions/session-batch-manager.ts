import { PromiseQueue } from './promise-queue'
import { SessionBatchRecorder } from './session-batch-recorder'

export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private queue: PromiseQueue<void>

    constructor() {
        this.currentBatch = new SessionBatchRecorder()
        this.queue = new PromiseQueue()
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
}
