export type AccountViewTileConfig = Record<string, unknown>

export interface AccountViewTileLogicProps {
    instanceId?: string
    initialConfig?: AccountViewTileConfig
    onConfigChange?: (config: AccountViewTileConfig) => void
}

export interface AccountViewWidgetProps extends AccountViewTileLogicProps {
    accountId: string
    externalId: string
    projectId?: number
    embedded?: boolean
}

export interface AccountViewTileConfigEditorProps {
    projectId: number
    accountId: string
    config: AccountViewTileConfig
    saving: boolean
    onChange: (config: AccountViewTileConfig) => void
}

export function getTileString(config: AccountViewTileConfig | undefined, key: string, fallback = ''): string {
    const value = config?.[key]
    return typeof value === 'string' ? value : fallback
}

export function getTileStringArray(config: AccountViewTileConfig | undefined, key: string): string[] {
    const value = config?.[key]
    return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : []
}

export function getTileRecord(config: AccountViewTileConfig | undefined, key: string): Record<string, unknown> | null {
    const value = config?.[key]
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}
