import { PluginConfigType, PluginType } from '~/types'

export interface PluginRepositoryEntry {
    name: string
    url: string
    description: string
    tag: string
    config?: Record<string, PluginConfigType>
}

export interface PluginTypeWithConfig extends PluginType {
    pluginConfig: PluginConfigType
}

export type PluginInstallationType = 'local' | 'custom' | 'repository'
