import { Hub, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { pluginDigest } from '../../utils/utils'

export async function loadPlugin(hub: Hub, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig

    if (!plugin) {
        pluginConfig.vm?.failInitialization!()
        return false
    }

    try {
        // load config json
        const configJson = plugin.source__plugin_json
        let config: PluginJsonConfig = {}
        if (configJson) {
            try {
                config = JSON.parse(configJson)
            } catch (e) {
                pluginConfig.vm?.failInitialization!()
                await processError(hub, pluginConfig, `Could not load "plugin.json" for ${pluginDigest(plugin)}`)
                return false
            }
        }

        // setup "backend" app
        const pluginSource = plugin.source__index_ts
        if (pluginSource) {
            void pluginConfig.vm?.initialize!(pluginSource, pluginDigest(plugin))
            return true
        } else {
            // always call this if no backend app present, will signal that the VM is done
            pluginConfig.vm?.failInitialization!()

            // if there is a frontend or site app, don't save an error if no backend app
            const hasFrontend = plugin['source__frontend_tsx']
            const hasSite = plugin['source__site_ts']

            if (!hasFrontend && !hasSite) {
                await processError(
                    hub,
                    pluginConfig,
                    `Could not load source code for ${pluginDigest(plugin)}. Tried: ${
                        config['main'] || 'index.ts, index.js'
                    }`
                )
                return false
            }
        }
    } catch (error) {
        pluginConfig.vm?.failInitialization!()
        await processError(hub, pluginConfig, error)
    }
    return false
}
