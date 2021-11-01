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
        if (plugin.url?.startsWith('file:')) {
            const pluginPath = path.resolve(server.BASE_DIR, plugin.url.substring(5))
            const configPath = path.resolve(pluginPath, 'plugin.json')

            let config: PluginJsonConfig = {}
            if (fs.existsSync(configPath)) {
                try {
                    const jsonBuffer = fs.readFileSync(configPath)
                    config = JSON.parse(jsonBuffer.toString())
                } catch (e) {
                    pluginConfig.vm?.failInitialization!()
                    await processError(
                        server,
                        pluginConfig,
                        `Could not load posthog config at "${configPath}" for ${pluginDigest(plugin)}`
                    )
                    return false
                }
            }

            if (!config['main'] && !fs.existsSync(path.resolve(pluginPath, 'index.js'))) {
                pluginConfig.vm?.failInitialization!()
                await processError(
                    server,
                    pluginConfig,
                    `No "main" config key or "index.js" file found for ${pluginDigest(plugin)}`
                )
                return false
            }

            const jsPath = path.resolve(pluginPath, config['main'] || 'index.js')
            const indexJs = fs.readFileSync(jsPath).toString()

            void pluginConfig.vm?.initialize!(
                server,
                pluginConfig,
                indexJs,
                `local ${pluginDigest(plugin)} from "${pluginPath}"!`
            )
            return true
        } else if (plugin.archive) {
            let config: PluginJsonConfig = {}
            const archive = Buffer.from(plugin.archive)
            const json = await getFileFromArchive(archive, 'plugin.json')
            if (json) {
                try {
                    config = JSON.parse(json)
                } catch (error) {
                    pluginConfig.vm?.failInitialization!()
                    await processError(server, pluginConfig, `Can not load plugin.json for ${pluginDigest(plugin)}`)
                    return false
                }
            }

            const indexJs = await getFileFromArchive(archive, config['main'] || 'index.js')

            if (indexJs) {
                void pluginConfig.vm?.initialize!(server, pluginConfig, indexJs, pluginDigest(plugin))
                return true
            } else {
                pluginConfig.vm?.failInitialization!()
                await processError(server, pluginConfig, `Could not load index.js for ${pluginDigest(plugin)}!`)
            }
        } else if (plugin.plugin_type === 'source' && plugin.source) {
            void pluginConfig.vm?.initialize!(server, pluginConfig, plugin.source, pluginDigest(plugin))
            return true
        } else {
            pluginConfig.vm?.failInitialization!()
            await processError(
                server,
                pluginConfig,
                `Tried using undownloaded remote ${pluginDigest(plugin)}, which is not supported!`
            )
        }
    } catch (error) {
        pluginConfig.vm?.failInitialization!()
        await processError(server, pluginConfig, error)
    }
    return false
}
