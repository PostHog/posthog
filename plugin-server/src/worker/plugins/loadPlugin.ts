import * as fs from 'fs'
import * as path from 'path'

import { Hub, Plugin, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { pluginDigest } from '../../utils/utils'

function readFileIfExists(baseDir: string, plugin: Plugin, file: string): string | null {
    const fullPath = path.resolve(baseDir, plugin.url!.substring(5), file)
    if (fs.existsSync(fullPath)) {
        return fs.readFileSync(fullPath).toString()
    }
    return null
}

export async function loadPlugin(hub: Hub, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig
    const isLocalPlugin = plugin?.plugin_type === 'local'

    if (!plugin) {
        pluginConfig.vm?.failInitialization!()
        return false
    }

    try {
        // load config json
        const configJson = isLocalPlugin
            ? readFileIfExists(hub.BASE_DIR, plugin, 'plugin.json')
            : plugin.source__plugin_json
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
        const pluginSource = isLocalPlugin
            ? config['main']
                ? readFileIfExists(hub.BASE_DIR, plugin, config['main'])
                : readFileIfExists(hub.BASE_DIR, plugin, 'index.js') ||
                  readFileIfExists(hub.BASE_DIR, plugin, 'index.ts')
            : plugin.source__index_ts
        if (pluginSource) {
            void pluginConfig.vm?.initialize!(pluginSource, pluginDigest(plugin))
            return true
        } else {
            // always call this if no backend app present, will signal that the VM is done
            pluginConfig.vm?.failInitialization!()

            // if there is a frontend or site app, don't save an error if no backend app
            const hasFrontend = isLocalPlugin
                ? readFileIfExists(hub.BASE_DIR, plugin, 'frontend.tsx')
                : plugin['source__frontend_tsx']
            const hasSite = isLocalPlugin
                ? readFileIfExists(hub.BASE_DIR, plugin, 'site.ts')
                : plugin['source__site_ts']

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
