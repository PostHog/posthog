export interface PluginRepositoryEntryConfig {
    name: string
    type: string
    default: any
}

export interface PluginRepositoryEntry {
    name: string
    url: string
    description: string
    config?: Record<string, PluginRepositoryEntryConfig>
}
