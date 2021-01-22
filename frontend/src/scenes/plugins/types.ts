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
    upgrades: PluginUpgradeType
}

export interface PluginUpgradeType {
    currentTag?: string
    nextTag?: string
    error?: boolean
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
