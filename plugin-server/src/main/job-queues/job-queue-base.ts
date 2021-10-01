import { EnqueuedJob, JobQueue, OnJobCallback, PluginsServerConfig } from '../../types'

export class JobQueueBase implements JobQueue {
    started: boolean
    paused: boolean
    onJob: OnJobCallback | null
    timeout: NodeJS.Timeout | null
    intervalSeconds: number

    constructor() {
        this.started = false
        this.paused = false
        this.onJob = null
        this.timeout = null
        this.intervalSeconds = 10
    }

    connectProducer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async connectProducer(): Promise<void> {
        throw new Error('connectProducer() not implemented for job queue!')
    }

    enqueue(retry: EnqueuedJob): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async enqueue(retry: EnqueuedJob): Promise<void> {
        throw new Error('enqueue() not implemented for job queue!')
    }

    disconnectProducer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async disconnectProducer(): Promise<void> {
        throw new Error('disconnectProducer() not implemented for job queue!')
    }

    startConsumer(onJob: OnJobCallback): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async startConsumer(onJob: OnJobCallback): Promise<void> {
        this.onJob = onJob
        if (!this.started) {
            this.started = true
            await this.syncState()
        }
    }

    stopConsumer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async stopConsumer(): Promise<void> {
        this.started = false
        await this.syncState()
    }

    pauseConsumer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async pauseConsumer(): Promise<void> {
        this.paused = true
        await this.syncState()
    }

    isConsumerPaused(): boolean {
        return this.paused
    }

    resumeConsumer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async resumeConsumer(): Promise<void> {
        if (this.paused) {
            this.paused = false
            await this.syncState()
        }
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    protected async readState(): Promise<boolean> {
        throw new Error('readState() not implemented for job queue!')
    }

    protected async syncState(): Promise<void> {
        if (this.started && !this.paused) {
            if (this.timeout) {
                clearTimeout(this.timeout)
            }
            // eslint-disable-next-line @typescript-eslint/await-thenable
            const hadSomething = await this.readState()
            this.timeout = setTimeout(() => this.syncState(), hadSomething ? 0 : this.intervalSeconds * 1000)
        } else {
            if (this.timeout) {
                clearTimeout(this.timeout)
            }
        }
    }
}
