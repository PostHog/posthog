import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginMethods } from '../../../types'
import { PluginInstance } from '../lazy'

export class NoopInlinePlugin implements PluginInstance {
    // The noop plugin has no initialization behavior, or imports
    initialize = async () => {}
    failInitialization = () => {}
    usedImports: Set<string> | undefined
    methods: PluginMethods

    hub: Hub
    config: PluginConfig

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.hub = hub
        this.config = pluginConfig
        this.usedImports = new Set()

        this.methods = {
            processEvent: (event: PluginEvent) => {
                return Promise.resolve(event)
            },
        }
    }

    public getTeardown(): Promise<PluginMethods['teardownPlugin'] | null> {
        return Promise.resolve(null)
    }

    public getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        return Promise.resolve(this.methods[method_name] as PluginMethods[T])
    }

    public clearRetryTimeoutIfExists = () => {}

    public setupPluginIfNeeded(): Promise<boolean> {
        return Promise.resolve(true)
    }

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        // TODO - this will be identical across all plugins, so figure out a better place to put it.
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.config,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }
}
