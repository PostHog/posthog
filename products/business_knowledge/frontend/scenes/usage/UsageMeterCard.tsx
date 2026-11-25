import { LemonCard } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

export interface UsageMeterBreakdownRow {
    key: string
    label: string
    total: number
}

export function UsageMeterCard({
    label,
    total,
    caption,
    seriesName,
    dailyCounts,
    dailyLabels,
    breakdownTitle,
    breakdown,
    loading,
}: {
    label: string
    total: number
    caption: string
    seriesName: string
    dailyCounts: number[]
    dailyLabels: string[]
    breakdownTitle: string
    breakdown: UsageMeterBreakdownRow[]
    loading: boolean
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex min-w-0 flex-col gap-2 p-3">
            <div className="flex flex-col gap-1">
                <span className="text-sm text-secondary">{label}</span>
                <span className="text-2xl font-semibold" translate="no">
                    {total.toLocaleString()}
                </span>
                <span className="text-xs text-muted">{caption}</span>
            </div>
            {total > 0 && (
                <Sparkline
                    type="bar"
                    className="h-16 w-full"
                    data={dailyCounts}
                    labels={dailyLabels}
                    name={seriesName}
                    loading={loading}
                />
            )}
            {breakdown.length > 0 && (
                <div className="flex flex-col gap-1 border-t border-primary pt-2">
                    <span className="text-xs text-muted">{breakdownTitle}</span>
                    {breakdown.map((row) => (
                        <div key={row.key} className="flex items-baseline justify-between gap-2 text-sm">
                            <span className="truncate">{row.label}</span>
                            <span className="font-medium" translate="no">
                                {row.total.toLocaleString()}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </LemonCard>
    )
}
