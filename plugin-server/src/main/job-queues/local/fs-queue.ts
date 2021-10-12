import { EnqueuedJob, JobQueue, OnJobCallback } from '../../../types'
import Timeout = NodeJS.Timeout
import * as fs from 'fs'
import * as path from 'path'

import { JobQueueBase } from '../job-queue-base'

export class FsQueue extends JobQueueBase {
    paused: boolean
    started: boolean
    interval: Timeout | null
    filename: string

    constructor(filename?: string) {
        super()

        if (process.env.NODE_ENV !== 'test') {
            throw new Error('Can not use FsQueue outside tests')
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

    enqueue(job: EnqueuedJob): Promise<void> | void {
        fs.appendFileSync(this.filename, `${JSON.stringify(job)}\n`)
    }

    startConsumer(onJob: OnJobCallback): void {
        super.startConsumer(onJob)
        fs.writeFileSync(this.filename, '')
    }

    async readState(): Promise<boolean> {
        const timestamp = new Date().valueOf()
        const queue = fs
            .readFileSync(this.filename)
            .toString()
            .split('\n')
            .filter((a) => a)
            .map((s) => JSON.parse(s) as EnqueuedJob)

        const newQueue = queue.filter((element) => element.timestamp < timestamp)

        if (newQueue.length > 0) {
            const oldQueue = queue.filter((element) => element.timestamp >= timestamp)
            fs.writeFileSync(this.filename, `${oldQueue.map((q) => JSON.stringify(q)).join('\n')}\n`)

            await this.onJob?.(newQueue)
            return true
        }

        return false
    }

    stopConsumer(): void {
        super.stopConsumer()
        fs.unlinkSync(this.filename)
    }
}
