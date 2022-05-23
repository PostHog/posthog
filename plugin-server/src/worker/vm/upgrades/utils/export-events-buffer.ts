import { Hub } from 'types'

export type BufferOptions = {
    limit: number
    timeoutSeconds: number
    onFlush?: (objects: any[], points: number) => void | Promise<void>
}

export class ExportEventsBuffer {
    buffer: any[]
    timeout: NodeJS.Timeout | null
    points: number
    options: BufferOptions
    hub: Hub

    constructor(hub: Hub, opts?: Partial<BufferOptions>) {
        this.buffer = []
        this.timeout = null
        this.points = 0
        this.options = {
            limit: 10,
            timeoutSeconds: 60,
            ...opts,
        }
        this.hub = hub
    }

    public async add(object: Record<string, any>, points = 1): Promise<void> {
        // flush existing if adding would make us go over the limit
        if (this.points && this.points + points > this.options.limit) {
            await this.flush()
        }

        // add the object to the buffer
        this.points += points
        this.buffer.push(object)

        if (this.points > this.options.limit) {
            // flush (again?) if we are now over the limit
            await this.flush()
        } else if (!this.timeout) {
            // if not, make sure there's a flush timeout
            this.timeout = setTimeout(async () => await this.flush(), this.options.timeoutSeconds * 1000)
        }
    }

    public async flush(): Promise<void> {
        this.hub.statsd?.increment(`buffer_voided_promises`, { instanceId: this.hub.instanceId.toString() })

        const oldBuffer = this.buffer
        const oldPoints = this.points
        this.buffer = []
        this.points = 0

        this.hub.promiseManager.trackPromise(this._flush(oldBuffer, oldPoints, new Date()))
        await this.hub.promiseManager.awaitPromisesIfNeeded()
    }

    public async _flush(oldBuffer: any[], oldPoints: number, timer: Date): Promise<void> {
        if (this.timeout) {
            clearTimeout(this.timeout)
            this.timeout = null
        }

        await this.options.onFlush?.(oldBuffer, oldPoints)
        this.hub.statsd?.timing(`buffer_promise_duration`, timer)
    }
}
