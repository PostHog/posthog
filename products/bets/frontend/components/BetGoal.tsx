import { Text } from '@posthog/quill'

import { TodayChange } from 'scenes/project-homepage/today/TodayChange'
import { TodaySparkline } from 'scenes/project-homepage/today/TodaySparkline'
import type { TodayTone } from 'scenes/project-homepage/today/todayTone'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import type { BetsDetailApi, BetsMetricApi } from '../generated/api.schemas'
import { metricPeriod, money, number } from '../lib/format'
import { BetGoalChart } from './BetGoalChart'
import { BetResourceLink } from './BetResourceLink'
import { BetSpendChart } from './BetSpendChart'

function GoalFact({ label, value, note }: { label: string; value: string; note?: string | false }): JSX.Element {
    return (
        <div className="Bets__goalFact flex min-w-0 flex-col gap-0.5">
            <dt>{label}</dt>
            <dd className="m-0 flex flex-col gap-0.5">
                <span className="Bets__goalFactValue tabular-nums">{value}</span>
                {note && <span className="Bets__goalFactNote whitespace-nowrap">{note}</span>}
            </dd>
        </div>
    )
}

function changeTone(bet: BetsDetailApi): TodayTone {
    const change = bet.metric.change
    if (!change) {
        return 'neutral'
    }
    return change > 0 === (bet.direction !== 'decrease') ? 'good' : 'risk'
}

function goalCaption(bet: BetsDetailApi): string {
    const { current, message, dates } = bet.metric
    if (current === null) {
        return message || 'The metric has no observations yet.'
    }
    const period = metricPeriod(dates)
    if (bet.target === null) {
        return period
    }
    const target = Number(bet.target)
    const remaining = bet.direction === 'decrease' ? current - target : target - current
    const progress = remaining <= 0 ? 'Target reached' : `${number(remaining, bet.unit)} to target`
    return [progress, period].filter(Boolean).join(' · ')
}

function hasTrend(values: number[]): boolean {
    return values.length > 1 && Math.min(...values) !== Math.max(...values)
}

function SecondaryMetric({
    name,
    insight,
    value,
}: {
    name: string
    insight: string
    value?: BetsMetricApi
}): JSX.Element {
    const current = value?.current ?? null
    return (
        <li className="Bets__goalSecondary flex min-w-0 flex-col items-start gap-0.5">
            <BetResourceLink
                kind="insight"
                title={name}
                href={urls.insightView(insight as InsightShortId)}
                id={insight}
            />
            <span
                className={`Bets__goalFactValue tabular-nums${current === null ? ' Bets__goalFactValue--empty' : ''}`}
            >
                {current === null ? 'No data yet' : number(current, value?.unit)}
            </span>
            {current === null && value?.message ? (
                <span className="Bets__goalFactNote whitespace-nowrap">{value.message}</span>
            ) : (
                value &&
                hasTrend(value.values) && (
                    <span className="mt-1 block h-5.5 w-full max-w-40">
                        <TodaySparkline
                            values={value.values}
                            labels={value.dates}
                            tone="neutral"
                            emphasizeLast={3}
                            formatValue={(point) => number(point, value.unit)}
                        />
                    </span>
                )
            )}
        </li>
    )
}

export function BetGoal({ bet }: { bet: BetsDetailApi }): JSX.Element {
    const current = bet.metric.current
    const open = bet.status !== 'closed'
    const overBudget = bet.money.available_cents < 0
    const comparison = bet.direction === 'decrease' ? '≤' : '≥'
    return (
        <section className="Bets__goal my-6 flex flex-col gap-6 py-6" aria-label="Goal and budget">
            <div className="Bets__goalMetric flex min-w-0 flex-col items-start gap-1">
                {bet.goal_insight ? (
                    <BetResourceLink
                        kind="insight"
                        title={bet.goal_metric}
                        href={urls.insightView(bet.goal_insight as InsightShortId)}
                        id={bet.goal_insight}
                    />
                ) : (
                    <Text size="sm" weight="medium">
                        {bet.goal_metric}
                    </Text>
                )}
                <div className="flex items-baseline gap-2">
                    <span
                        className={`Bets__goalValue tabular-nums${current === null ? ' Bets__goalValue--empty' : ''}`}
                    >
                        {current === null ? 'No data yet' : number(current, bet.unit)}
                    </span>
                    {current !== null && <TodayChange change={bet.metric.change} tone={changeTone(bet)} />}
                </div>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {goalCaption(bet)}
                </Text>
            </div>
            <div className="Bets__goalPanels grid gap-x-10 gap-y-5">
                <div className="Bets__goalPanel flex min-w-0 flex-col gap-3.5">
                    <BetGoalChart bet={bet} />
                    <dl className="m-0 grid grid-flow-col gap-x-7 gap-y-0" aria-label="Progress">
                        {bet.target !== null && (
                            <GoalFact label="Target" value={`${comparison} ${number(Number(bet.target), bet.unit)}`} />
                        )}
                        {bet.baseline_value !== null && (
                            <GoalFact label="Started at" value={number(bet.baseline_value, bet.unit)} />
                        )}
                        <GoalFact
                            label="Ideas tested"
                            value={String(bet.ideas_tried)}
                            note={bet.ideas_tried > 0 && `${bet.ideas_won} won`}
                        />
                    </dl>
                </div>
                <div className="Bets__goalPanel flex min-w-0 flex-col gap-3.5">
                    <BetSpendChart bet={bet} />
                    <dl className="m-0 grid grid-flow-col gap-x-7 gap-y-0" aria-label="Budget">
                        {open && (
                            <GoalFact
                                label="Budget"
                                value={money(bet.money.allocated_cents)}
                                note={
                                    bet.money.reserved_cents > 0 && `${money(bet.money.reserved_cents)} held for work`
                                }
                            />
                        )}
                        <GoalFact
                            label="Spent"
                            value={money(bet.money.spent_cents)}
                            note={
                                bet.spend_pending
                                    ? 'Usage still settling'
                                    : !open && `of ${money(bet.money.allocated_cents)} budget`
                            }
                        />
                        {open && (
                            <GoalFact
                                label={overBudget ? 'Over budget' : 'Left'}
                                value={money(Math.abs(bet.money.available_cents))}
                            />
                        )}
                    </dl>
                </div>
            </div>
            {!!bet.secondary_metrics.length && (
                <div className="Bets__goalSecondaries flex flex-col gap-3 pt-5">
                    <Text size="sm" weight="medium" render={<h3 className="m-0" />}>
                        Secondary metrics
                    </Text>
                    <ul className="m-0 grid list-none gap-x-7 gap-y-4 p-0">
                        {bet.secondary_metrics.map((metric, index) => (
                            <SecondaryMetric
                                key={metric.insight}
                                name={metric.name}
                                insight={metric.insight}
                                value={bet.secondary_values[index]}
                            />
                        ))}
                    </ul>
                </div>
            )}
        </section>
    )
}
