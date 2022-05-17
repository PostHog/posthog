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

            const readFile = (file: string): string | null => {
                const fullPath = path.resolve(pluginPath, file)
                return fs.existsSync(fullPath) ? fs.readFileSync(fullPath).toString() : null
            }

            const configJson: string | null = readFile('plugin.json')
            let config: PluginJsonConfig = {}

            if (configJson) {
                try {
                    config = JSON.parse(configJson)
                } catch (e) {
                    pluginConfig.vm?.failInitialization!()
                    await processError(
                        server,
                        pluginConfig,
                        `Could not load app config from "plugin.json" for ${pluginDigest(plugin)}`
                    )
                    return false
                }
            }

            let pluginSource: string | null = null
            if (config['main']) {
                pluginSource = readFile(config['main'])
            } else {
                pluginSource = readFile('index.ts') || readFile('index.js')
            }

            if (!pluginSource) {
                pluginConfig.vm?.failInitialization!()
                await processError(
                    server,
                    pluginConfig,
                    `Could not load source from for ${pluginDigest(plugin)}. Tried: ${
                        config['main'] || 'index.ts and index.js'
                    }`
                )
                return false
            }

            void pluginConfig.vm?.initialize!(pluginSource, `local ${pluginDigest(plugin)} from "${pluginPath}"!`)
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

            let pluginSource: string | null = null
            if (config['main']) {
                pluginSource = await getFileFromArchive(archive, config['main'])
            } else {
                pluginSource =
                    (await getFileFromArchive(archive, 'index.ts')) || (await getFileFromArchive(archive, 'index.js'))
            }

            if (pluginSource) {
                void pluginConfig.vm?.initialize!(pluginSource, pluginDigest(plugin))
                return true
            } else {
                pluginConfig.vm?.failInitialization!()
                await processError(server, pluginConfig, `Could not load index.js for ${pluginDigest(plugin)}!`)
            }
        } else if (plugin.plugin_type === 'source' && plugin.source) {
            void pluginConfig.vm?.initialize!(plugin.source, pluginDigest(plugin))
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
