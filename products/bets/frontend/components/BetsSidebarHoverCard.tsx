import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { Skeleton, Text, cn } from '@posthog/quill'

import type { TodayTone } from 'scenes/project-homepage/today/todayTone'

import type { BetsEntryApi } from '../generated/api.schemas'
import { type BetRating, betPerformance } from '../lib/betPerformance'
import { BET_STATUS_LABELS } from '../lib/betStatus'
import { money, number, progressPercent } from '../lib/format'
import { betsSidebarPreviewLogic } from '../logics/betsSidebarPreviewLogic'
import { BET_RATING_CLASSES } from './betRatingClasses'
import { BetSparkline } from './BetSparkline'

const RATING_TONES: Record<BetRating, TodayTone> = {
    bad: 'neutral',
    meh: 'neutral',
    good: 'good',
    amazing: 'good',
}

export function BetsSidebarHoverCard({ bet }: { bet: BetsEntryApi }): JSX.Element {
    const { spendHistories } = useValues(betsSidebarPreviewLogic)
    const { loadSpendHistory } = useActions(betsSidebarPreviewLogic)
    const history = spendHistories[bet.id]
    useEffect(() => {
        loadSpendHistory(bet.id)
    }, [bet.id, loadSpendHistory])
    const spendValues = useMemo(() => history?.map((point) => point.spent_cents) ?? [], [history])
    const spendLabels = useMemo(() => history?.map((point) => point.at) ?? [], [history])
    const performance = betPerformance(bet)
    const tone = performance ? RATING_TONES[performance.rating] : 'neutral'
    const target = Number.parseFloat(bet.target ?? '')
    const comparison = bet.direction === 'decrease' ? '≤' : '≥'
    const overBudget = bet.money.available_cents < 0
    return (
        <div className="flex flex-col gap-3 p-2.5" data-attr="bets-sidebar-hover-card">
            <div className="flex min-w-0 flex-col">
                <span className="text-xs leading-4 font-semibold wrap-anywhere">{bet.title}</span>
                <Text size="xs" variant="muted" render={<span />} className="truncate">
                    {[BET_STATUS_LABELS[bet.status], bet.note].filter(Boolean).join(' · ')}
                </Text>
            </div>
            <section aria-label="Goal" className="flex min-w-0 flex-col gap-1">
                <div className="flex min-w-0 items-baseline gap-1.5 text-xs">
                    <Text size="xs" variant="muted" render={<span />} className="min-w-0 flex-1 truncate">
                        {bet.goal_metric || bet.metric.name}
                    </Text>
                    {performance && (
                        <span className={cn('shrink-0 tabular-nums', BET_RATING_CLASSES[performance.rating])}>
                            {progressPercent(performance.progress)}
                        </span>
                    )}
                </div>
                <div className="flex min-w-0 items-baseline gap-1">
                    <span className="text-sm leading-5 font-semibold tabular-nums">
                        {number(bet.metric.current, bet.unit)}
                    </span>
                    {Number.isFinite(target) && (
                        <Text size="xs" variant="muted" render={<span />} className="min-w-0 truncate tabular-nums">
                            target {comparison} {number(target, bet.unit)}
                        </Text>
                    )}
                </div>
                {bet.metric.values.length > 1 && (
                    <BetSparkline
                        label={bet.goal_metric || bet.metric.name}
                        values={bet.metric.values}
                        labels={bet.metric.dates}
                        limit={Number.isFinite(target) ? target : null}
                        tone={tone}
                    />
                )}
            </section>
            <section aria-label="Budget" className="flex min-w-0 flex-col gap-1">
                <div className="flex min-w-0 items-baseline gap-1.5">
                    <Text size="xs" variant="muted" render={<span />} className="min-w-0 flex-1 truncate">
                        Budget
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="shrink-0 tabular-nums">
                        {overBudget
                            ? `${money(Math.abs(bet.money.available_cents))} over`
                            : `${money(bet.money.available_cents)} left`}
                    </Text>
                </div>
                <div className="flex min-w-0 items-baseline gap-1">
                    <span className="text-sm leading-5 font-semibold tabular-nums">{money(bet.money.spent_cents)}</span>
                    <Text size="xs" variant="muted" render={<span />} className="min-w-0 truncate tabular-nums">
                        spent of {money(bet.money.allocated_cents)}
                    </Text>
                </div>
                {!history ? (
                    <Skeleton className="h-8 w-full" />
                ) : spendValues.length > 1 ? (
                    <BetSparkline
                        label="Spent"
                        values={spendValues}
                        labels={spendLabels}
                        limit={bet.money.allocated_cents}
                        floor={0}
                        tone={overBudget ? 'risk' : 'neutral'}
                    />
                ) : (
                    spendValues.length === 0 && (
                        <Text size="xs" variant="muted" render={<span />}>
                            No usage yet
                        </Text>
                    )
                )}
                {(bet.money.reserved_cents > 0 || bet.spend_pending) && (
                    <Text size="xs" variant="muted" render={<span />} className="truncate">
                        {bet.spend_pending
                            ? 'Usage still settling'
                            : `${money(bet.money.reserved_cents)} held for running work`}
                    </Text>
                )}
            </section>
        </div>
    )
}
