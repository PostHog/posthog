import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType } from '../../types'
import { processError } from '../../utils/db/error'

export async function teardownPlugins(server: Hub, pluginConfig?: PluginConfig): Promise<void> {
    const pluginConfigs = pluginConfig ? [pluginConfig] : server.pluginConfigs.values()

    const teardownPromises: Promise<void>[] = []
    for (const pluginConfig of pluginConfigs) {
        if (pluginConfig.instance) {
            pluginConfig.instance.clearRetryTimeoutIfExists()
            const teardownPlugin = await pluginConfig.instance.getTeardown()
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

    await Promise.all(teardownPromises)
}
