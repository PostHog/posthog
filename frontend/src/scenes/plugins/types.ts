import { PluginConfigType, PluginType } from '~/types'

export interface PluginRepositoryEntry {
    name: string
    url: string
    description: string
    tag: string
    config?: Record<string, PluginConfigType>
    maintainer?: string
    type?: PluginRepositoryEntryType
}

export enum PluginRepositoryEntryType {
    DataIn = 'data_in',
    DataOut = 'data_out',
}

export interface PluginTypeWithConfig extends PluginType {
    pluginConfig: PluginConfigType
    updateStatus: PluginUpdateStatusType
    hasMoved?: boolean
}

export interface PluginUpdateStatusType {
    upToDate?: boolean
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
    Advanced = 'advanced',
}
