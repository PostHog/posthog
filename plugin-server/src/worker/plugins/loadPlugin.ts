import * as fs from 'fs'
import * as path from 'path'

import { Hub, Plugin, PluginConfig, PluginJsonConfig } from '../../types'
import { processError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { pluginDigest } from '../../utils/utils'
import { transpileFrontend, transpileWeb } from '../frontend/transpile'

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

        const transpileIfNeeded = async ({
            type,
            filename,
            pluginKey,
            transpile,
        }: {
            type: 'frontend' | 'web'
            filename: 'frontend.tsx' | 'web.ts'
            pluginKey: 'source__frontend_tsx' | 'source__web_ts'
            transpile: (source: string) => string
        }): Promise<boolean> => {
            const source = isLocalPlugin ? readFileIfExists(hub.BASE_DIR, plugin, filename) : plugin[pluginKey]
            if (source) {
                if (await hub.db.getPluginTranspilationLock(plugin.id, filename)) {
                    status.info('🔌', `Transpiling ${pluginDigest(plugin)}`)
                    const transpilationStartTimer = new Date()
                    try {
                        const transpiled = transpile(source)
                        await hub.db.setPluginTranspiled(plugin.id, filename, transpiled)
                    } catch (error: any) {
                        await processError(hub, pluginConfig, error)
                        await hub.db.setPluginTranspiledError(
                            plugin.id,
                            filename,
                            typeof error === 'string'
                                ? error
                                : [error.message, error.stack].filter((a) => !!a).join('\n')
                        )
                        hub.statsd?.increment(`transpile_${type}.ERROR`, {
                            plugin: plugin.name ?? '?',
                            pluginId: `${plugin.id ?? '?'}`,
                        })
                    }
                    hub.statsd?.timing(`transpile_${type}`, transpilationStartTimer, {
                        plugin: plugin.name ?? '?',
                        pluginId: `${plugin.id ?? '?'}`,
                    })
                }
            }
            return !!source
        }

        const hasFrontend = await transpileIfNeeded({
            type: 'frontend',
            filename: 'frontend.tsx',
            pluginKey: 'source__frontend_tsx',
            transpile: transpileFrontend,
        })

        const hasWeb = await transpileIfNeeded({
            type: 'web',
            filename: 'web.ts',
            pluginKey: 'source__web_ts',
            transpile: transpileWeb,
        })

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

            // if we transpiled a frontend app, don't save an error if no backend app
            if (!hasFrontend && !hasWeb) {
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
