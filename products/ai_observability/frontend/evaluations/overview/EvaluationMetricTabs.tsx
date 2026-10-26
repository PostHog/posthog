import { useActions, useValues } from 'kea'

import { LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { formatPercent, formatPoints } from './evaluationOverviewDisplay'
import { type OverviewMetric, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

interface MetricTab {
    metric: OverviewMetric
    label: string
    value: string
    change: number | null
    formatChange: (value: number) => string
    /** Which direction of change is good. Null for a count, where neither direction is good or bad on its own. */
    goodDirection: 'up' | 'down' | null
    changeTooltip: string
}

function percentChange(current: number, previous: number): number | null {
    return previous > 0 ? ((current - previous) / previous) * 100 : null
}

function ChangePill({ tab }: { tab: MetricTab }): JSX.Element | null {
    if (tab.change === null || !Number.isFinite(tab.change)) {
        return null
    }
    const up = tab.change > 0
    const good = tab.goodDirection === null || tab.change === 0 ? null : up === (tab.goodDirection === 'up')
    return (
        <Tooltip title={tab.changeTooltip}>
            <span
                className={cn(
                    'inline-flex items-center gap-0.5 text-xs font-medium tabular-nums',
                    good === null ? 'text-secondary' : good ? 'text-success' : 'text-danger'
                )}
            >
                {tab.change !== 0 && (up ? <IconArrowUp /> : <IconArrowDown />)}
                {/* The arrow carries the direction, so the number drops its sign. */}
                {tab.formatChange(Math.abs(tab.change)).replace(/^[+-]/, '')}
            </span>
        </Tooltip>
    )
}

export function EvaluationMetricTabs(): JSX.Element {
    const { overview, rows, metric } = useValues(evaluationsOverviewLogic)
    const { selectCard } = useActions(evaluationsOverviewLogic)
    const passRates = overview?.passRateOverview
    const totals = overview?.totals
    const sentiment = totals?.sentiment

    const tabs: MetricTab[] = [
        {
            metric: 'pass_rate',
            label: 'Pass rate',
            value: passRates?.median != null ? formatPercent(passRates.median) : '-',
            change: passRates?.medianComparison
                ? passRates.medianComparison.current - passRates.medianComparison.previous
                : null,
            formatChange: formatPoints,
            goodDirection: 'up',
            changeTooltip: 'Change in the median against the previous period, for evaluations with results in both',
        },
        {
            metric: 'graded',
            label: 'Graded results',
            value: totals && totals.graded > 0 ? humanFriendlyNumber(totals.graded) : '-',
            change: totals?.gradedComparison
                ? percentChange(totals.gradedComparison.current, totals.gradedComparison.previous)
                : null,
            formatChange: (value) => `${value.toFixed(1)}%`,
            goodDirection: null,
            changeTooltip: 'Change against the previous period, for evaluations with results in both',
        },
    ]
    if (rows.some((row) => row.summary.kind === 'sentiment')) {
        tabs.push({
            metric: 'sentiment',
            label: 'Negative sentiment',
            value: sentiment ? `${Math.round(sentiment.negativeShare)}%` : '-',
            change:
                sentiment && sentiment.previousShare !== null
                    ? sentiment.negativeShare - sentiment.previousShare
                    : null,
            formatChange: formatPoints,
            goodDirection: 'down',
            changeTooltip: 'Change in the share of negative user messages against the previous period',
        })
    }

    return (
        <LemonTabs
            activeKey={metric}
            onChange={selectCard}
            barClassName="mb-0"
            tabs={tabs.map((tab) => ({
                key: tab.metric,
                label: (
                    <span className="flex flex-col items-start">
                        <span className="text-xs font-normal">{tab.label}</span>
                        <span className="flex items-baseline gap-2 text-primary">
                            <span className="text-xl font-semibold tabular-nums">{tab.value}</span>
                            <ChangePill tab={tab} />
                        </span>
                    </span>
                ),
                'data-attr': `evaluation-overview-tab-${tab.metric}`,
            }))}
        />
    )
}
