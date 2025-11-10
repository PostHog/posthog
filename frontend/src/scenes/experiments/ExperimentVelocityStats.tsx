import { useValues } from 'kea'

import { IconInfo, IconTrending } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown } from 'lib/lemon-ui/icons'

import { experimentsLogic } from './experimentsLogic'

export function ExperimentVelocityStats(): JSX.Element | null {
    const { experimentsStats, experimentsStatsLoading } = useValues(experimentsLogic)

    if (experimentsStatsLoading) {
        return (
            <div className="p-4 border rounded bg-bg-light flex items-center justify-center" style={{ minHeight: 100 }}>
                <Spinner />
            </div>
        )
    }

    const { launched_last_30d, percent_change, active_experiments, completed_last_30d } = experimentsStats

    if (launched_last_30d <= 3) {
        return null
    }

    const isPositive = percent_change > 0
    const isNegative = percent_change < 0
    const arrow = isPositive ? <IconTrending fontSize="16" /> : isNegative ? <IconTrendingDown fontSize="16" /> : ''
    const changeColor = isPositive ? 'text-success' : isNegative ? 'text-danger' : 'text-text-secondary'

    return (
        <div className="px-4 py-3 border rounded bg-bg-light flex items-center gap-6">
            <div className="metric-cell-header font-semibold flex items-center gap-1">
                Experimentation velocity (last 30d)
                <Tooltip title="Shows your team's experimentation velocity: how many experiments you're launching, running, and completing. Launched count is compared to the previous 30 days to track growth.">
                    <IconInfo className="text-muted-alt" fontSize="16" />
                </Tooltip>
            </div>
            <div className="h-4 w-px bg-border" />
            <div className="flex items-baseline gap-2 metric-cell">
                <span className="text-lg font-semibold">{launched_last_30d}</span>
                <span>launched</span>
                {percent_change !== 0 && (
                    <span className={`metric-cell font-bold ${changeColor}`}>
                        {arrow} {Math.abs(percent_change)}%
                    </span>
                )}
            </div>
            <div>•</div>
            <div className="flex items-baseline gap-2 metric-cell">
                <span className="text-lg font-semibold">{active_experiments}</span>
                <span className="">active</span>
            </div>
            <div>•</div>
            <div className="flex items-baseline gap-2 metric-cell">
                <span className="text-lg font-bold">{completed_last_30d}</span>
                <span>completed</span>
            </div>
        </div>
    )
}
