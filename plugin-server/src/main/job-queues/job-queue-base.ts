import { TaskList } from 'graphile-worker'

import { EnqueuedJob, JobQueue } from '../../types'

export class JobQueueBase implements JobQueue {
    started: boolean
    paused: boolean
    jobHandlers: TaskList
    timeout: NodeJS.Timeout | null
    intervalSeconds: number

    constructor() {
        this.started = false
        this.paused = false
        this.jobHandlers = {}
        this.timeout = null
        this.intervalSeconds = 10
    }

    connectProducer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async connectProducer(): Promise<void> {
        throw new Error('connectProducer() not implemented for job queue!')
    }

    enqueue(jobName: string, job: EnqueuedJob): void
    // eslint-disable-next-line @typescript-eslint/require-await, @typescript-eslint/no-unused-vars
    async enqueue(jobName: string, job: EnqueuedJob): Promise<void> {
        throw new Error('enqueue() not implemented for job queue!')
    }

    disconnectProducer(): void
    // eslint-disable-next-line @typescript-eslint/require-await
    async disconnectProducer(): Promise<void> {
        throw new Error('disconnectProducer() not implemented for job queue!')
    }

    startConsumer(jobHandlers: TaskList): void
    async startConsumer(jobHandlers: TaskList): Promise<void> {
        this.jobHandlers = jobHandlers
        if (!this.started) {
            this.started = true
            await this.syncState()
        }
    }

    stopConsumer(): void
    async stopConsumer(): Promise<void> {
        this.started = false
        await this.syncState()
    }

    pauseConsumer(): void
    async pauseConsumer(): Promise<void> {
        this.paused = true
        await this.syncState()
    }

    isConsumerPaused(): boolean {
        return this.paused
    }

    resumeConsumer(): void
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
            const hadSomething = await this.readState()
            this.timeout = setTimeout(() => this.syncState(), hadSomething ? 0 : this.intervalSeconds * 1000)
        } else {
            if (this.timeout) {
                clearTimeout(this.timeout)
            }
        }
    }
}
