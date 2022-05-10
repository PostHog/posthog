import * as fs from 'fs'
import * as path from 'path'

import { Hub, Plugin, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { getFileFromArchive, pluginDigest } from '../../utils/utils'
import { transpileFrontend } from './transpile'

export async function loadPlugin(hub: Hub, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig

    if (!plugin) {
        pluginConfig.vm?.failInitialization!()
        return false
    }

    try {
        if (plugin.url?.startsWith('file:')) {
            const pluginPath = path.resolve(hub.BASE_DIR, plugin.url.substring(5))
            const configPath = path.resolve(pluginPath, 'plugin.json')

            let config: PluginJsonConfig = {}
            if (fs.existsSync(configPath)) {
                try {
                    const jsonBuffer = fs.readFileSync(configPath)
                    config = JSON.parse(jsonBuffer.toString())
                } catch (e) {
                    pluginConfig.vm?.failInitialization!()
                    await processError(
                        hub,
                        pluginConfig,
                        `Could not load posthog config at "${configPath}" for ${pluginDigest(plugin)}`
                    )
                    return false
                }
            }

            if (!config['main'] && !fs.existsSync(path.resolve(pluginPath, 'index.js'))) {
                pluginConfig.vm?.failInitialization!()
                await processError(
                    hub,
                    pluginConfig,
                    `No "main" config key or "index.js" file found for ${pluginDigest(plugin)}`
                )
                return false
            }

            const jsPath = path.resolve(pluginPath, config['main'] || 'index.js')
            const indexJs = fs.readFileSync(jsPath).toString()

            void pluginConfig.vm?.initialize!(indexJs, `local ${pluginDigest(plugin)} from "${pluginPath}"!`)
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
                    await processError(hub, pluginConfig, `Can not load plugin.json for ${pluginDigest(plugin)}`)
                    return false
                }
            }

            const indexJs = await getFileFromArchive(archive, config['main'] || 'index.js')

            if (indexJs) {
                void pluginConfig.vm?.initialize!(indexJs, pluginDigest(plugin))
                return true
            } else {
                pluginConfig.vm?.failInitialization!()
                await processError(hub, pluginConfig, `Could not load index.js for ${pluginDigest(plugin)}!`)
            }
        } else if (plugin.plugin_type === 'source') {
            if (
                plugin.source_frontend &&
                (plugin.transpiled_frontend === null || plugin.transpiled_frontend === undefined)
            ) {
                if (await getTranspilationLock(hub, plugin)) {
                    try {
                        plugin.transpiled_frontend = transpileFrontend(plugin.source_frontend)
                    } catch (error: any) {
                        plugin.transpiled_frontend = "'error'"
                        await processError(hub, pluginConfig, error)
                    }
                    await hub.db.postgresQuery(
                        'update posthog_plugin set transpiled_frontend = $1 where id = $2',
                        [plugin.transpiled_frontend, plugin.id],
                        'setPluginTranspiledFrontend'
                    )
                }
            }

            if (plugin.source) {
                void pluginConfig.vm?.initialize!(plugin.source, pluginDigest(plugin))
                return true
            }

            if (!plugin.source && !plugin.transpiled_frontend) {
                pluginConfig.vm?.failInitialization!()
                await processError(hub, pluginConfig, `Could not load source code for ${pluginDigest(plugin)}!`)
            }
        } else {
            pluginConfig.vm?.failInitialization!()
            await processError(
                hub,
                pluginConfig,
                `Tried using undownloaded remote ${pluginDigest(plugin)}, which is not supported!`
            )
        }
    } catch (error) {
        pluginConfig.vm?.failInitialization!()
        await processError(hub, pluginConfig, error)
    }
    return false
}

export async function getTranspilationLock(hub: Hub, plugin: Plugin): Promise<boolean> {
    // Only update `transpiled_frontend` if it equals NULL at the time of the update.
    const response = await hub.db.postgresQuery(
        'UPDATE posthog_plugin SET transpiled_frontend = $1 ' +
            'WHERE id = $2 AND transpiled_frontend IS NULL RETURNING transpiled_frontend',
        ["'transpiling'", plugin.id],
        'getPluginTranspiledFrontendLock'
    )
    return response.rowCount > 0
}
