import { PluginConfigSchema } from '@posthog/plugin-scaffold'

import { Hub, PluginCapabilities, PluginConfig, PluginLogLevel } from '../../../types'
import { upsertInlinePlugin } from '../../../utils/db/sql'
import { status } from '../../../utils/status'
import { PluginInstance } from '../lazy'
import { NoopInlinePlugin } from './noop'

export function constructInlinePluginInstance(hub: Hub, pluginConfig: PluginConfig): PluginInstance {
    const plugin = INLINE_PLUGIN_MAP.get(pluginConfig.plugin?.url || '')
    if (!plugin) {
        throw new Error(`Inline plugin constructor not found for ${pluginConfig.plugin?.name}`)
    }
    return plugin.constructor(hub, pluginConfig)
}

export interface RegisteredInlinePlugin {
    constructor: (hub: Hub, config: PluginConfig) => PluginInstance
    description: Readonly<InlinePluginDescription>
}

// TODO - add all inline plugins here
export const INLINE_PLUGIN_MAP: Map<string, RegisteredInlinePlugin> = new Map([
    [
        'inline://noop',
        {
            constructor: (hub: Hub, config: PluginConfig) => new NoopInlinePlugin(hub, config),
            description: {
                name: 'Noop Plugin',
                description: 'A plugin that does nothing',
                is_global: false,
                is_preinstalled: false,
                url: 'inline://noop',
                config_schema: {},
                tag: 'noop',
                capabilities: {},
                is_stateless: true,
                log_level: PluginLogLevel.Info,
            },
        },
    ],
])

// Inline plugins are uniquely identified by their /url/, not their ID, and do
// not have most of the standard plugin properties. This reduced interface is
// the "canonical" description of an inline plugin, but can be mapepd to a region
// specific Plugin object by url.
export interface InlinePluginDescription {
    name: string
    description: string
    is_global: boolean
    is_preinstalled: boolean
    url: string
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    tag: string
    capabilities: PluginCapabilities
    is_stateless: boolean
    log_level: PluginLogLevel
}

export async function syncInlinePlugins(hub: Hub): Promise<void> {
    status.info('⚡', 'Syncing inline plugins')
    for (const [_, plugin] of INLINE_PLUGIN_MAP) {
        await upsertInlinePlugin(hub, plugin.description)
    }
}
