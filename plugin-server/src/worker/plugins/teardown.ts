import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType } from '../../types'
import { processError } from '../../utils/db/error'

export function teardownPlugins(server: Hub) {
    server.pluginConfigs.reset()
    server.pluginConfigsPerTeam.reset()
}

export async function teardownPluginConfig(
    server: Hub,
    pluginConfig: PluginConfig,
    teardownPromises: Promise<void>[] = []
) {
    if (pluginConfig.vm) {
        pluginConfig.vm.clearRetryTimeoutIfExists()
        const teardownPlugin = await pluginConfig.vm.getTeardownPlugin()
        if (teardownPlugin) {
            teardownPromises.push(
                (async () => {
                    try {
                        await teardownPlugin()
                        await server.db.queuePluginLogEntry({
                            pluginConfig,
                            source: PluginLogEntrySource.System,
                            type: PluginLogEntryType.Debug,
                            message: `Plugin unloaded (instance ID ${server.instanceId}).`,
                            instanceId: server.instanceId,
                        })
                    } catch (error) {
                        await processError(server, pluginConfig, error)
                        await server.db.queuePluginLogEntry({
                            pluginConfig,
                            source: PluginLogEntrySource.System,
                            type: PluginLogEntryType.Error,
                            message: `Plugin failed to unload (instance ID ${server.instanceId}).`,
                            instanceId: server.instanceId,
                        })
                    }
                })()
            )
        } else {
            await server.db.queuePluginLogEntry({
                pluginConfig,
                source: PluginLogEntrySource.System,
                type: PluginLogEntryType.Debug,
                message: `Plugin unloaded (instance ID ${server.instanceId}).`,
                instanceId: server.instanceId,
            })
        }
    }
}

export async function teardownPluginConfigPromise(server: Hub, pluginConfigPromise: Promise<PluginConfig | undefined>) {
    const pluginConfig = await pluginConfigPromise
    if (pluginConfig) {
        await teardownPluginConfig(server, pluginConfig)
    }
}
