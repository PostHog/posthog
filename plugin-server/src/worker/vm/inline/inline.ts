import { Hub, PluginConfig } from 'types'

import { PluginInstance } from '../lazy'
import { NoopInlinePlugin } from './noop'

export function constructInlinePluginInstance(hub: Hub, pluginConfig: PluginConfig): PluginInstance {
    // TODO - handle this properly - you should actually just early-return if the plugin url doesn't exist
    const constructor = INLINE_PLUGIN_MAP.get(pluginConfig.plugin?.url || '')
    if (!constructor) {
        throw new Error(`Inline plugin constructor not found for ${pluginConfig.plugin?.name}`)
    }
    return constructor(hub, pluginConfig)
}

// TODO - add all inline plugins here
export const INLINE_PLUGIN_MAP: Map<string, (hub: Hub, config: PluginConfig) => PluginInstance> = new Map([
    ['inline://noop', (hub: Hub, config: PluginConfig) => new NoopInlinePlugin(hub, config)],
])
