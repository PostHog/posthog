import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function MonitoringMetricCard({
    label,
    value,
    description,
    loading,
}: {
    label: string
    value: string
    description: string
    loading: boolean
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="min-h-32 p-4">
            <div className="text-sm font-semibold text-muted-alt">{label}</div>
            {loading ? (
                <LemonSkeleton className="my-3 h-8 w-24" />
            ) : (
                <div className="my-2 truncate text-3xl font-bold tabular-nums">{value}</div>
            )}
            <div className="text-xs text-muted">{description}</div>
        </LemonCard>
    )
}
