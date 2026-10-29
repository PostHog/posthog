import { type CSSProperties, useMemo } from 'react'

import { Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import type { BetsDetailApi, BetsResultsApi } from '../generated/api.schemas'
import { money, number } from '../lib/format'
import { effectAxis, effectX, elapsed } from '../lib/results'
import { BetEffectAxis } from './BetEffectAxis'
import { BetGoalChart } from './BetGoalChart'
import { BetIdeaNumber } from './BetIdeaNumber'
import type { BetIdeaPin } from './BetIdeaPins'
import { BetIdeaResultRow } from './BetIdeaResultRow'
import { BetResourceLink } from './BetResourceLink'

function Fact({ label, value, note }: { label: string; value: string; note?: string }): JSX.Element {
    return (
        <div className="Bets__goalFact flex min-w-0 flex-col gap-0.5">
            <dt>{label}</dt>
            <dd className="m-0 flex flex-col gap-0.5">
                <span className="Bets__goalFactValue tabular-nums">{value}</span>
                {note && <span className="Bets__goalFactNote">{note}</span>}
            </dd>
        </div>
    )
}

function moment(value: string | null): string {
    return value ? dayjs(value).format('MMM D, h:mm A') : ''
}

function plural(count: number, word: string): string {
    return `${count} ${count === 1 ? word : `${word}s`}`
}

function headline(bet: BetsDetailApi, results: BetsResultsApi, target: string): { value: string; note: string } {
    const start = bet.baseline_value
    const end = results.final_value
    const missing = results.recorded ? '' : ' Final value not recorded.'
    const short = results.values.length < 2 ? ' Too few observations for a chart.' : ''
    if (start !== null && end !== null) {
        return {
            value: `${number(start, bet.unit)} → ${number(end, bet.unit)}`,
            note: `${target}.${results.recorded ? '' : ' The end value is the latest reading. Final value not recorded.'}`,
        }
    }
    if (end !== null) {
        return { value: number(end, bet.unit), note: `latest value, ${target}.${short}` }
    }
    if (start !== null) {
        return { value: number(start, bet.unit), note: `starting value, ${target}.${missing}` }
    }
    return { value: 'No data', note: `${target}.${missing}` }
}

function guardrailLine(bet: BetsDetailApi, results: BetsResultsApi): string {
    if (!bet.secondary_metrics.length) {
        return ''
    }
    const names = bet.secondary_metrics.map((metric) => metric.name).join(', ')
    const harmed = results.ideas.filter((idea) => idea.harmed_guardrails.length)
    if (harmed.length) {
        const ideas = harmed.map((idea) => `Idea ${idea.number ?? ''}`.trim()).join(', ')
        return `Guardrail: ${names}. ${ideas} harmed it and ${harmed.length === 1 ? 'was' : 'were'} stopped.`
    }
    return results.spend.tested_ideas ? `Guardrail: ${names}. No experiment harmed it.` : `Guardrail: ${names}.`
}

export function BetResults({ bet, results }: { bet: BetsDetailApi; results: BetsResultsApi }): JSX.Element {
    const comparison = bet.direction === 'decrease' ? '≤' : '≥'
    const target = bet.target === null ? 'no target' : `target ${comparison} ${number(Number(bet.target), bet.unit)}`
    const top = headline(bet, results, target)
    const axis = useMemo(
        () => (results.ideas.some((idea) => idea.effect) ? effectAxis(results.ideas) : null),
        [results.ideas]
    )
    const zeroStyle = useMemo(
        () => (axis ? ({ '--interval-zero': String(effectX(0, axis, 1)) } as CSSProperties) : undefined),
        [axis]
    )
    const pins: BetIdeaPin[] = useMemo(
        () =>
            results.ideas.flatMap((idea, index) =>
                idea.finished_at
                    ? [
                          {
                              number: idea.number ?? index + 1,
                              at: idea.finished_at,
                              label: idea.title,
                              highlighted: idea.outcome === 'won',
                          },
                      ]
                    : []
            ),
        [results.ideas]
    )
    const chartBet = useMemo(
        () => ({ ...bet, metric: { ...bet.metric, dates: results.dates, values: results.values } }),
        [bet, results.dates, results.values]
    )
    const { spend } = results
    const stopped = bet.work.filter((item) => item.kind === 'tracking' && item.stage === 'dropped')
    const guardrail = guardrailLine(bet, results)
    return (
        <>
            <section className="Bets__goal BetsResults my-6 flex flex-col gap-5 py-6" aria-label="Results">
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
                    <div className="flex flex-wrap items-baseline gap-2">
                        <span className="Bets__goalValue tabular-nums">{top.value}</span>
                        <Text size="sm" variant="muted" render={<span />}>
                            {top.note}
                        </Text>
                    </div>
                </div>
                {results.values.length > 1 && <BetGoalChart bet={chartBet} pins={pins} />}
                <dl className="BetsResults__facts m-0 grid gap-x-7 gap-y-4" aria-label="Summary">
                    <Fact
                        label="Started at"
                        value={number(bet.baseline_value, bet.unit)}
                        note={bet.baseline_at ? moment(bet.baseline_at) : 'Not measured'}
                    />
                    <Fact
                        label={results.recorded ? 'Ended at' : 'Latest'}
                        value={number(results.final_value, bet.unit)}
                        note={results.recorded ? moment(results.final_at) : 'Final value not recorded'}
                    />
                    {bet.target !== null && (
                        <Fact label="Target" value={`${comparison} ${number(Number(bet.target), bet.unit)}`} />
                    )}
                    {results.ended_at && (
                        <Fact label="Time taken" value={elapsed(results.started_at, results.ended_at)} />
                    )}
                    <Fact
                        label="Spent"
                        value={money(bet.money.spent_cents)}
                        note={`of ${money(bet.money.allocated_cents)} budget`}
                    />
                </dl>
                {guardrail && <p className="m-0 text-xs text-muted-foreground">{guardrail}</p>}
            </section>
            <section className="mt-6" aria-label="Ideas tried">
                <h2 className="Bets__sectionTitle">Ideas tried</h2>
                {!results.ideas.length && (
                    <Text size="sm" variant="muted" render={<p className="mt-3 mb-0" />}>
                        No ideas were tested. This bet does not tell us if the belief is true.
                    </Text>
                )}
                {(results.ideas.length > 0 || stopped.length > 0) && (
                    <ul className="BetsResults__ideas" data-plot={axis ? '' : undefined}>
                        {results.ideas.map((idea, index) => (
                            <BetIdeaResultRow
                                key={idea.id}
                                idea={idea}
                                position={index + 1}
                                axis={axis}
                                first={index === 0}
                            />
                        ))}
                        {stopped.map((item, index) => (
                            <li key={item.id} className="BetsResults__idea">
                                <span className="BetsResults__number">
                                    <BetIdeaNumber number={null} />
                                </span>
                                <div className="min-w-0">
                                    <span className="TodayRow__title">{item.title}</span>
                                    <p className="BetsResults__meta">
                                        <span className="BetsResults__outcome">Stopped</span>
                                        {item.note && <span>{item.note}</span>}
                                    </p>
                                </div>
                                {axis && (
                                    <div
                                        className="BetsResults__plot"
                                        data-first={(!results.ideas.length && index === 0) || undefined}
                                        style={zeroStyle}
                                    >
                                        <span className="BetsResults__zero" />
                                    </div>
                                )}
                            </li>
                        ))}
                        {axis && <BetEffectAxis axis={axis} metric={bet.goal_metric} />}
                    </ul>
                )}
            </section>
            <section className="mt-8" aria-label="Spend">
                <h2 className="Bets__sectionTitle">Spend</h2>
                <dl className="BetsResults__facts m-0 mt-3 grid gap-x-7 gap-y-4">
                    {spend.scout_cents > 0 && (
                        <Fact
                            label="Finding ideas"
                            value={money(spend.scout_cents)}
                            note={plural(spend.scout_runs, 'scout run')}
                        />
                    )}
                    {results.ideas.length > 0 && (
                        <Fact
                            label="Building and testing"
                            value={money(spend.ideas_cents)}
                            note={plural(results.ideas.length, 'idea')}
                        />
                    )}
                    <Fact label="Checking tracking" value={money(spend.tracking_cents)} />
                    {spend.per_tested_idea_cents !== null && (
                        <Fact
                            label="Per idea tested"
                            value={money(spend.per_tested_idea_cents)}
                            note="search included"
                        />
                    )}
                </dl>
                {spend.returned_cents > 0 && (
                    <p className="m-0 mt-3 text-xs text-muted-foreground">
                        Bets returned {money(spend.returned_cents)} of unused budget.
                    </p>
                )}
            </section>
        </>
    )
}
