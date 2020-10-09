import { PluginConfig } from '~/types'

export interface PluginRepositoryEntry {
    name: string
    url: string
    description: string
    config?: Record<string, PluginConfig>
}
