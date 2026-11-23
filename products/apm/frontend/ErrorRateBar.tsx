import type { HealthStatusEnumApi } from './generated/api.schemas'
import { formatPercent } from './healthDisplay'

const BAR_COLOR: Record<HealthStatusEnumApi, string> = {
    good: 'bg-success',
    warning: 'bg-warning',
    serious: 'bg-danger',
    critical: 'bg-danger',
}

export function ErrorRateBar({
    errorRate,
    status,
}: {
    errorRate: number | null
    status: HealthStatusEnumApi
}): JSX.Element {
    // A rate under 1% would draw no bar at all, so any error keeps a sliver visible.
    const width = errorRate ? Math.max(errorRate * 100, 2) : 0
    return (
        <div className="inline-flex flex-col items-end gap-0.5 min-w-16">
            <span className="font-mono">{formatPercent(errorRate)}</span>
            <div className="h-1 w-full rounded bg-fill-secondary overflow-hidden">
                <div className={`h-full ${BAR_COLOR[status]}`} style={{ width: `${Math.min(width, 100)}%` }} />
            </div>
        </div>
    )
}
