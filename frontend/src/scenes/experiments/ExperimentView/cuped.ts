export type CupedSelection = 'default' | 'enabled' | 'disabled'

type CupedConfig = { enabled?: boolean; lookback_days?: number } | null | undefined

export function getCupedSelection(cuped: CupedConfig): CupedSelection {
    const explicit = cuped?.enabled
    if (explicit === undefined) {
        return 'default'
    }
    return explicit ? 'enabled' : 'disabled'
}

export function resolveCupedEnabled(cuped: CupedConfig, teamDefaultEnabled: boolean): boolean {
    return cuped?.enabled === undefined ? teamDefaultEnabled : !!cuped.enabled
}
