import { JobHelpers, TaskList } from 'graphile-worker'

import { EnqueuedJob } from '../../../types'
import Timeout = NodeJS.Timeout
import * as fs from 'fs'
import * as path from 'path'

interface FsJob {
    jobName: string
    timestamp: number
    type?: string
    payload?: Record<string, any>
    eventPayload?: Record<string, any>
    pluginConfigId?: number
    pluginConfigTeam?: number
}
export class MockGraphileWorker {
    interval: Timeout | null
    filename: string

    started: boolean
    paused: boolean
    jobHandlers: TaskList
    timeout: NodeJS.Timeout | null
    intervalSeconds: number

    constructor(filename?: string) {
        this.started = false
        this.paused = false
        this.jobHandlers = {}
        this.timeout = null
        this.intervalSeconds = 10

        if (process.env.NODE_ENV !== 'test') {
            throw new Error('Cannot use MockGraphileWorker outside tests')
        }
        this.paused = false
        this.started = false
        this.interval = null
        this.filename = filename || path.join(process.cwd(), 'tmp', 'fs-queue.txt')
    }

    connectProducer(): void {
        fs.mkdirSync(path.dirname(this.filename), { recursive: true })
        fs.writeFileSync(this.filename, '')
    }

    disconnectProducer(): void {
        // nothing to do
    }

    enqueue(jobName: string, job: EnqueuedJob): Promise<void> | void {
        fs.appendFileSync(this.filename, `${JSON.stringify({ jobName, ...job })}\n`)
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

    async start(jobHandlers: TaskList): Promise<void> {
        this.jobHandlers = jobHandlers
        if (!this.started) {
            this.started = true
            await this.syncState()
        }
        fs.writeFileSync(this.filename, '')
    }

    async readState(): Promise<boolean> {
        const timestamp = new Date().valueOf()
        const queue = fs
            .readFileSync(this.filename)
            .toString()
            .split('\n')
            .filter((a) => a)
            .map((s) => JSON.parse(s) as FsJob)

        const jobsQueue = queue.filter((element) => element.timestamp < timestamp)

        if (jobsQueue.length > 0) {
            const oldQueue = queue.filter((element) => element.timestamp >= timestamp)
            fs.writeFileSync(this.filename, `${oldQueue.map((q) => JSON.stringify(q)).join('\n')}\n`)

            for (const job of jobsQueue) {
                await this.jobHandlers[job.jobName](job, {} as JobHelpers)
            }
            return true
        }

        return false
    }

    async stop(): Promise<void> {
        this.started = false
        await this.syncState()
        fs.unlinkSync(this.filename)
    }

    async resumeConsumer(): Promise<void> {
        if (this.paused) {
            this.paused = false
            await this.syncState()
        }
    }

    async pause(): Promise<void> {
        this.paused = true
        await this.syncState()
    }

    isPaused(): boolean {
        return this.paused
    }
}
