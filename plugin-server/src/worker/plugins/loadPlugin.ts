import * as fs from 'fs'
import * as path from 'path'

import { Hub, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { getFileFromArchive, pluginDigest } from '../../utils/utils'

export async function loadPlugin(server: Hub, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig

    if (!plugin) {
        pluginConfig.vm?.failInitialization!()
        return false
    }

    try {
        let getFile = (file: string): Promise<string | null> => Promise.resolve(null)

        if (plugin.url?.startsWith('file:')) {
            const pluginPath = path.resolve(server.BASE_DIR, plugin.url.substring(5))
            getFile = (file) => {
                const fullPath = path.resolve(pluginPath, file)
                return Promise.resolve(fs.existsSync(fullPath) ? fs.readFileSync(fullPath).toString() : null)
            }
        } else if (plugin.archive) {
            const archive = Buffer.from(plugin.archive)
            getFile = (file) => getFileFromArchive(archive, file)
        } else if (plugin.plugin_type === 'source') {
            getFile = async (file) => {
                if (file === 'index.ts' && plugin.source) {
                    return plugin.source
                }
                return await server.db.getPluginSource(plugin.id, file)
            }
        } else {
            pluginConfig.vm?.failInitialization!()
            await processError(
                server,
                pluginConfig,
                `Plugin ${pluginDigest(plugin)} is not a local, remote or source plugin. Can not load.`
            )
            return false
        }

        const configJson: string | null = await getFile('plugin.json')
        let config: PluginJsonConfig = {}

        if (configJson) {
            try {
                config = JSON.parse(configJson)
            } catch (e) {
                pluginConfig.vm?.failInitialization!()
                await processError(server, pluginConfig, `Could not load "plugin.json" for ${pluginDigest(plugin)}`)
                return false
            }
        }

        const pluginSource = config['main']
            ? await getFile(config['main'])
            : (await getFile('index.ts')) || (await getFile('index.js'))

        if (!pluginSource) {
            pluginConfig.vm?.failInitialization!()
            await processError(
                server,
                pluginConfig,
                `Could not load source code for ${pluginDigest(plugin)}. Tried: ${
                    config['main'] || 'index.ts, index.js'
                }`
            )
            return false
        }

        void pluginConfig.vm?.initialize!(pluginSource, pluginDigest(plugin))
        return true
    } catch (error) {
        pluginConfig.vm?.failInitialization!()
        await processError(server, pluginConfig, error)
    }
    return false
}
