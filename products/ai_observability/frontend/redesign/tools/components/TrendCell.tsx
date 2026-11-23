import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface TrendCellProps {
    current: number
    previous: number
    /** Plural noun for the tooltip: "calls". */
    unit: string
}

// Doubling and halving are the same size of change, so both earn the tag.
const BIG_GROWTH_PCT = 100
const BIG_DROP_PCT = -50

export function TrendCell({ current, previous, unit }: TrendCellProps): JSX.Element {
    if (previous === 0) {
        return (
            <Tooltip title={`${humanFriendlyNumber(current)} ${unit}, none in the previous period`}>
                <span tabIndex={0}>
                    <LemonTag type="highlight" size="small">
                        New
                    </LemonTag>
                </span>
            </Tooltip>
        )
    }
    const change = Math.round(((current - previous) / previous) * 100)
    const label = `${change > 0 ? '+' : ''}${change.toLocaleString()}%`
    return (
        <Tooltip
            title={`${humanFriendlyNumber(current)} ${unit} vs ${humanFriendlyNumber(previous)} in the previous period`}
        >
            <span className="tabular-nums" tabIndex={0}>
                {change >= BIG_GROWTH_PCT || change <= BIG_DROP_PCT ? (
                    <LemonTag type="highlight" size="small">
                        {label}
                    </LemonTag>
                ) : (
                    label
                )}
            </span>
        </Tooltip>
    )
}
