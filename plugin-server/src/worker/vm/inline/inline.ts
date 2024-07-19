import { PluginConfigSchema } from '@posthog/plugin-scaffold'

import { Hub, PluginCapabilities, PluginConfig, PluginLogLevel } from '../../../types'
import { upsertInlinePlugin } from '../../../utils/db/sql'
import { status } from '../../../utils/status'
import { PluginInstance } from '../lazy'
import { NoopInlinePlugin } from './noop'
import { SEMVER_FLATTENER_CONFIG_SCHEMA, SemverFlattener } from './semver-flattener'

export function constructInlinePluginInstance(hub: Hub, pluginConfig: PluginConfig): PluginInstance {
    const url = pluginConfig.plugin?.url

    if (!INLINE_PLUGIN_URLS.includes(url as InlinePluginId)) {
        throw new Error(`Invalid inline plugin URL: ${url}`)
    }
    const plugin = INLINE_PLUGIN_MAP[url as InlinePluginId]

    return plugin.constructor(hub, pluginConfig)
}

export interface RegisteredInlinePlugin {
    constructor: (hub: Hub, config: PluginConfig) => PluginInstance
    description: Readonly<InlinePluginDescription>
}

export const INLINE_PLUGIN_URLS = ['inline://noop', 'inline://semver-flattener'] as const
type InlinePluginId = (typeof INLINE_PLUGIN_URLS)[number]

// TODO - add all inline plugins here
export const INLINE_PLUGIN_MAP: Record<InlinePluginId, RegisteredInlinePlugin> = {
    'inline://noop': {
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

    'inline://semver-flattener': {
        constructor: (hub: Hub, config: PluginConfig) => new SemverFlattener(hub, config),
        description: {
            name: 'posthog-semver-flattener',
            description:
                'Processes specified properties to flatten sematic versions. Assumes any property contains a string which matches [the SemVer specification](https://semver.org/#backusnaur-form-grammar-for-valid-semver-versions)',
            is_global: false,
            is_preinstalled: false,
            url: 'inline://semver-flattener',
            config_schema: SEMVER_FLATTENER_CONFIG_SCHEMA,
            tag: 'semver-flattener',
            capabilities: {
                jobs: [],
                scheduled_tasks: [],
                methods: ['processEvent'],
            },
            is_stateless: false, // TODO - this plugin /could/ be stateless, but right now we cache config parsing, which is stateful
            log_level: PluginLogLevel.Info,
        },
    },
}

// Inline plugins are uniquely identified by their /url/, not their ID, and do
// not have most of the standard plugin properties. This reduced interface is
// the "canonical" description of an inline plugin, but can be mapped to a region
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
    for (const url of INLINE_PLUGIN_URLS) {
        const plugin = INLINE_PLUGIN_MAP[url]
        await upsertInlinePlugin(hub, plugin.description)
    }
}
