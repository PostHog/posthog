/**
 * Legacy types from the deprecated @posthog/plugin-scaffold package (v1.4.4).
 * These supported the old plugin system. Do not use in new code.
 */

export type Properties = Record<string, any>

type ConfigDependencyArrayValue = string | undefined
type ConfigDependencySubArray = ConfigDependencyArrayValue[]
type ConfigDependencyArray = ConfigDependencySubArray[]

export interface PluginConfigStructure {
    key?: string
    name?: string
    default?: string
    hint?: string
    markdown?: string
    order?: number
    required?: boolean
    secret?: boolean
    required_if?: ConfigDependencyArray
    visible_if?: ConfigDependencyArray
}

export interface PluginConfigDefault extends PluginConfigStructure {
    type?: 'string' | 'json' | 'attachment'
}

export interface PluginConfigChoice extends PluginConfigStructure {
    type: 'choice'
    choices: string[]
}

export type PluginConfigSchema = PluginConfigDefault | PluginConfigChoice
