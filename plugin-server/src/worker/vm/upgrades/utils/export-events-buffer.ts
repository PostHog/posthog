import { Hub } from 'types'

export type BufferOptions = {
    limit: number
    timeoutSeconds: number
    onFlush?: (objects: any[], points: number) => void | Promise<void>
}

export class ExportEventsBuffer {
    buffer: any[]
    timeout: NodeJS.Timeout | null
    lastFlushTriggered: Date
    points: number
    options: BufferOptions
    hub: Hub

    constructor(hub: Hub, opts?: Partial<BufferOptions>) {
        this.buffer = []
        this.timeout = null
        this.lastFlushTriggered = new Date()
        this.points = 0
        this.options = {
            limit: 10,
            timeoutSeconds: 60,
            ...opts,
        }
        this.hub = hub
    }

    public async add(object: any, points = 1): Promise<void> {
        // flush existing if adding would make us go over the limit
        if (this.points && this.points + points > this.options.limit) {
            await this.triggerFlushInstrumented()
        }

        // add the object to the buffer
        this.points += points
        this.buffer.push(object)

        if (this.points > this.options.limit) {
            // flush (again?) if we are now over the limit
            await this.triggerFlushInstrumented()
        } else if (!this.timeout) {
            // if not, make sure there's a flush timeout
            this.timeout = setTimeout(
                async () => await this.triggerFlushInstrumented(),
                this.options.timeoutSeconds * 1000
            )
        }
    }

    private async triggerFlushInstrumented(): Promise<void> {
        this.hub.statsd?.increment(`buffer_voided_promises`)
        this.lastFlushTriggered = new Date()
        await this.hub.promiseManager.trackPromise(this.flush())
    }

    public async flush(): Promise<void> {
        if (this.timeout) {
            clearTimeout(this.timeout)
            this.timeout = null
        }
        if (this.buffer.length > 0 || this.points !== 0) {
            const oldBuffer = this.buffer
            const oldPoints = this.points
            this.buffer = []
            this.points = 0
            await this.options.onFlush?.(oldBuffer, oldPoints)
        }
        this.hub.statsd?.decrement(`buffer_voided_promises`)
        this.hub.statsd?.timing(`buffer_promise_duration`, this.lastFlushTriggered)
    }
}
