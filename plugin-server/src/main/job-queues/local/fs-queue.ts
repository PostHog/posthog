import { JobHelpers, TaskList } from 'graphile-worker'

import { EnqueuedJob } from '../../../types'
import Timeout = NodeJS.Timeout
import * as fs from 'fs'
import * as path from 'path'

import { JobQueueBase } from '../job-queue-base'

interface FsJob {
    jobName: string
    timestamp: number
    type?: string
    payload?: Record<string, any>
    eventPayload?: Record<string, any>
    pluginConfigId?: number
    pluginConfigTeam?: number
}
export class FsQueue extends JobQueueBase {
    paused: boolean
    started: boolean
    interval: Timeout | null
    filename: string

    constructor(filename?: string) {
        super()

        if (process.env.NODE_ENV !== 'test') {
            throw new Error('Cannot use FsQueue outside tests')
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

    startConsumer(jobHandlers: TaskList): void {
        super.startConsumer(jobHandlers)
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

    stopConsumer(): void {
        super.stopConsumer()
        fs.unlinkSync(this.filename)
    }
}
