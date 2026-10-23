import { useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ResultChangeApi } from '../../generated/api.schemas'
import { compactHeadline, formatPercent, formatPoints, resultHeadline } from './evaluationOverviewDisplay'
import { type RankedRow, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

function formatChange(change: ResultChangeApi): string {
    return change.unit === 'pp'
        ? formatPoints(change.value)
        : `${change.value > 0 ? '+' : ''}${change.value.toFixed(2)} points`
}

export function EvaluationRankedBars({
    items,
    labelHeader,
    valueHeader = 'Pass rate',
    fullScale = false,
}: {
    items: RankedRow[]
    labelHeader: string
    valueHeader?: string
    /** Draw on 0-100% instead of zooming in, for results with no shared meaning to compare closely. */
    fullScale?: boolean
}): JSX.Element {
    const { evaluationUrl } = useValues(evaluationsOverviewLogic)
    // Worst first, with results too sparse to rely on kept at the bottom and out of the scale.
    const sorted = [...items].sort((a, b) => Number(a.row.lowEvidence) - Number(b.row.lowEvidence) || a.rate - b.rate)
    const lowest = Math.min(100, ...sorted.filter((item) => !item.row.lowEvidence).map((item) => item.rate))
    // Start the scale just under the lowest value, so differences between high rates stay visible.
    const start = fullScale ? 0 : Math.max(0, Math.floor((lowest - 5) / 10) * 10)
    const position = (rate: number): string => `${Math.max(0, ((rate - start) / (100 - start)) * 100)}%`

    return (
        <div className="flex flex-col text-sm">
            <div className="flex items-center gap-3 text-xs text-secondary pb-1 border-b">
                <span className="w-28 @2xl:w-44 shrink-0">{labelHeader}</span>
                <span className="flex-1 flex justify-between">
                    <span>{`${start}%`}</span>
                    <span>100%</span>
                </span>
                <span className="w-28 @2xl:w-60 shrink-0 text-right">{valueHeader}</span>
            </div>
            {sorted.map(({ row, rate }) => {
                // The bar sits on the shared scale, and the label says the result in its own terms.
                const valueLabel =
                    row.summary.kind === 'pass_rate'
                        ? formatPercent(rate)
                        : row.summary.kind === 'score'
                          ? resultHeadline(row)
                          : compactHeadline(row)
                const change = row.change ? formatChange(row.change) : null
                return (
                    <Tooltip
                        key={row.id}
                        title={
                            <>
                                <div className="font-semibold">{row.name}</div>
                                <div>{`${row.summary.kind === 'pass_rate' ? `${valueLabel} passed` : valueLabel}, ${humanFriendlyNumber(row.gradedCount)} graded`}</div>
                                {change !== null && <div>{`${change} against the previous period`}</div>}
                                {row.lowEvidence && <div>Too few results to rely on</div>}
                            </>
                        }
                    >
                        <Link
                            to={evaluationUrl(row.id)}
                            subtle
                            className="flex items-center gap-3 py-1 rounded text-primary hover:bg-surface-secondary"
                            data-attr="evaluation-overview-ranked-bar"
                        >
                            <span className="w-28 @2xl:w-44 shrink-0 truncate text-left">{row.name}</span>
                            <span className="relative flex-1 min-w-8 h-2.5 rounded-sm bg-surface-secondary">
                                <span
                                    className={cn(
                                        'absolute inset-y-0 left-0 rounded-sm bg-muted',
                                        row.lowEvidence && 'opacity-40'
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: position(rate) }}
                                />
                            </span>
                            <span className="w-28 @2xl:w-60 shrink-0 text-right tabular-nums whitespace-nowrap truncate">
                                <span className={cn('font-semibold', row.lowEvidence && 'text-secondary')}>
                                    {valueLabel}
                                </span>
                                <span className="hidden @2xl:inline text-xs text-secondary ml-1">
                                    {change ?? `${humanFriendlyNumber(row.gradedCount)} graded`}
                                </span>
                            </span>
                        </Link>
                    </Tooltip>
                )
            })}
        </div>
    )
}
