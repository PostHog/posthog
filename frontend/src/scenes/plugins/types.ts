import { PluginConfigType, PluginType } from '~/types'

export interface PluginRepositoryEntry {
    name: string
    url: string
    description: string
    tag: string
    config?: Record<string, PluginConfigType>
    maintainer?: string
}

export interface PluginTypeWithConfig extends PluginType {
    pluginConfig: PluginConfigType
    updates: PluginUpdateType
}

export interface PluginUpdateType {
    currentTag?: string
    nextTag?: string
    error?: boolean
    updated?: boolean
}

export enum PluginInstallationType {
    Local = 'local',
    Custom = 'custom',
    Repository = 'repository',
    Source = 'source',
}

export enum PluginTab {
    Installed = 'installed',
    Repository = 'repository',
    Custom = 'custom',
}
