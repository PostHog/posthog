import * as fs from 'fs'
import * as path from 'path'

import { Hub, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { getFileFromArchive, pluginDigest } from '../../utils/utils'
import { transpileFrontend } from '../frontend/transpile'

export async function loadPlugin(hub: Hub, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig

    if (!plugin) {
        pluginConfig.vm?.failInitialization!()
        return false
    }

    try {
        let getFile: (file: string) => Promise<string | null> = () => Promise.resolve(null)
        if (plugin.url?.startsWith('file:')) {
            const pluginPath = path.resolve(hub.BASE_DIR, plugin.url.substring(5))
            getFile = (file) => {
                const fullPath = path.resolve(pluginPath, file)
                return Promise.resolve(fs.existsSync(fullPath) ? fs.readFileSync(fullPath).toString() : null)
            }
        } else if (plugin.archive) {
            const archive = Buffer.from(plugin.archive)
            getFile = (file) => getFileFromArchive(archive, file)
        } else if (plugin.plugin_type === 'source') {
            getFile = async (file) => {
                if (file === 'index.ts' && plugin.source__index_ts) {
                    return plugin.source__index_ts
                } else if (file === 'frontend.tsx' && plugin.source__frontend_tsx) {
                    return plugin.source__frontend_tsx
                }
                return await hub.db.getPluginSource(plugin.id, file)
            }
        } else {
            pluginConfig.vm?.failInitialization!()
            await processError(
                hub,
                pluginConfig,
                `Plugin ${pluginDigest(plugin)} is not a local, remote or source plugin. Cannot load.`
            )
            return false
        }

        // load config json
        const configJson: string | null = await getFile('plugin.json')
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

        // transpile "frontend" app if needed
        const frontendFilename = 'frontend.tsx'
        const pluginFrontend = await getFile(frontendFilename)
        if (pluginFrontend) {
            if (await hub.db.getPluginTranspilationLock(plugin.id, frontendFilename)) {
                status.info('🔌', `Transpiling ${pluginDigest(plugin)}`)
                const transpilationStartTimer = new Date()
                try {
                    const transpiled = transpileFrontend(pluginFrontend)
                    await hub.db.setPluginTranspiled(plugin.id, frontendFilename, transpiled)
                } catch (error: any) {
                    await processError(hub, pluginConfig, error)
                    await hub.db.setPluginTranspiledError(
                        plugin.id,
                        frontendFilename,
                        typeof error === 'string' ? error : [error.message, error.stack].filter((a) => !!a).join('\n')
                    )
                    hub.statsd?.increment(`transpile_frontend.ERROR`, {
                        plugin: plugin.name ?? '?',
                        pluginId: `${plugin.id ?? '?'}`,
                    })
                }
                hub.statsd?.timing(`transpile_frontend`, transpilationStartTimer, {
                    plugin: plugin.name ?? '?',
                    pluginId: `${plugin.id ?? '?'}`,
                })
            }
        }

        // setup "backend" app
        const pluginSource = config['main']
            ? await getFile(config['main'])
            : (await getFile('index.ts')) || (await getFile('index.js'))
        if (pluginSource) {
            void pluginConfig.vm?.initialize!(pluginSource, pluginDigest(plugin))
            return true
        } else {
            // always call this if no backend app present, will signal that the VM is done
            pluginConfig.vm?.failInitialization!()

            // if we transpiled a frontend app, don't save an error if no backend app
            if (!pluginFrontend) {
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
