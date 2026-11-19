import type { DeploymentVersionApi } from './generated/api.schemas'

export function formatChange(metric: 'error' | 'p95', row: DeploymentVersionApi): string | null {
    if (metric === 'error') {
        const change = row.error_rate_change
        if (change === null || change === undefined || Math.abs(change) < 0.0005) {
            return null
        }
        return `${change > 0 ? '+' : '−'}${(Math.abs(change) * 100).toFixed(1)} pts`
    }
    const change = row.p95_change_pct
    if (change === null || change === undefined || Math.abs(change) < 1) {
        return null
    }
    return `${change > 0 ? '+' : '−'}${Math.abs(change).toFixed(0)}%`
}
