import { runInTransaction } from '../../../../sentry'
import { Hub, PluginConfig } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'

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
    pluginConfig: PluginConfig
    hub: Hub

    constructor(hub: Hub, pluginConfig: PluginConfig, opts?: Partial<BufferOptions>) {
        this.buffer = []
        this.timeout = null
        this.points = 0
        this.options = {
            limit: 10,
            timeoutSeconds: 60,
            ...opts,
        }
        this.pluginConfig = pluginConfig
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
        const oldBuffer = this.buffer
        const oldPoints = this.points
        this.buffer = []
        this.points = 0

        this.hub.promiseManager.trackPromise(
            this._flush(oldBuffer, oldPoints, new Date()),
            'ExportEventsBuffer flush logs'
        )
        await this.hub.promiseManager.awaitPromisesIfNeeded()
    }

    public async _flush(oldBuffer: any[], oldPoints: number, _: Date): Promise<void> {
        if (this.timeout) {
            clearTimeout(this.timeout)
            this.timeout = null
        }

        const slowTimeout = timeoutGuard(
            `ExportEventsBuffer flush promise running for more than 5 minutes`,
            {
                plugin_id: this.pluginConfig.plugin_id,
                team_id: this.pluginConfig.team_id,
                plugin_config_id: this.pluginConfig.id,
            },
            300_000
        )
        try {
            await runInTransaction(
                {
                    name: 'export-events-buffer',
                    op: 'ExportEventsBuffer.flush',
                },
                async () => {
                    await this.options.onFlush?.(oldBuffer, oldPoints)
                }
            )
        } finally {
            clearTimeout(slowTimeout)
        }
    }
}
