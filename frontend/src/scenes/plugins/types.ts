import { PluginConfigType, PluginType } from '~/types'

export interface PluginRepositoryEntry {
    name: string
    url: string
    icon: string
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

export enum PluginTab {
    Apps = 'apps',
    AppsManagement = 'apps_management',
    BatchExports = 'batch_exports',
    History = 'history',
}
