import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import {
    AnalyticsMetricCard,
    type AnalyticsMetricCardProps,
} from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { formatBucket, formatPercent, formatPoints, toChartValues } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/**
 * A metric card that keeps its shape when there is nothing to show: a dash, an empty sparkline area and the
 * empty message as its caption, so the row of cards reads the same with or without data.
 */
function Tile({ buckets, ...props }: AnalyticsMetricCardProps & { buckets: string[] }): JSX.Element {
    if (props.value != null && Number.isFinite(props.value)) {
        const format = props.formatValue
        // Hovering a bucket without results would otherwise print "NaN%".
        return (
            <AnalyticsMetricCard
                {...props}
                formatValue={(value) => (Number.isFinite(value) ? (format ? format(value) : String(value)) : '-')}
            />
        )
    }
    return (
        <AnalyticsMetricCard
            {...props}
            value={NaN}
            formatValue={() => '-'}
            data={buckets.map(() => NaN)}
            labels={buckets}
            subtitle={undefined}
            restingSubtitle={props.emptyMessage}
            showChange={false}
            change={null}
        />
    )
}

function percentChange(current: number, previous: number): number | null {
    return previous > 0 ? ((current - previous) / previous) * 100 : null
}

export function EvaluationOverviewTiles(): JSX.Element {
    const theme = useChartTheme()
    const {
        overview,
        overviewLoading,
        request,
        buckets,
        interval,
        periodLength,
        rows,
        metric,
        attentionCounts,
        sentimentRow,
        measuredPassRateRows: counted,
    } = useValues(evaluationsOverviewLogic)
    const { selectCard } = useActions(evaluationsOverviewLogic)
    // Volume going up or down is not good or bad on its own, so its pill stays neutral.
    const neutral = useMemo(() => ({ background: 'transparent', foreground: getColorVar('muted') }), [])

    const loading = (overviewLoading || !request.ready) && !overview
    const passRates = overview?.passRateOverview
    const totals = overview?.totals
    const medianChange = passRates?.medianComparison
        ? passRates.medianComparison.current - passRates.medianComparison.previous
        : null
    const gradedChange = totals?.gradedComparison
        ? percentChange(totals.gradedComparison.current, totals.gradedComparison.previous)
        : null
    const sentiment = totals?.sentiment
    const hasSentimentEvaluation = rows.some((row) => row.summary.kind === 'sentiment')
    const shared = {
        theme,
        formatLabel: (label: string) => formatBucket(label, interval),
        sparklineHeight: 36,
        buckets,
        labels: buckets,
        loading,
    }

    return (
        <div className={cn('grid gap-3 grid-cols-2', hasSentimentEvaluation ? '@4xl:grid-cols-4' : '@3xl:grid-cols-3')}>
            <Tile
                {...shared}
                title="Needs attention"
                value={overview ? attentionCounts.any : undefined}
                formatValue={(value) => String(Math.round(value))}
                showChange={false}
                restingSubtitle={`of ${pluralize(rows.length, 'evaluation')}`}
                // Clicking scrolls to the list instead of selecting a chart, so the card is never shown as selected.
                selected={false}
                // The shared card grows its header to push a sparkline down. Without one, that would push the count
                // to the bottom, out of line with the cards next to it.
                className="[&>button>div>div:first-child]:flex-none"
                onClick={() => selectCard('attention')}
                ariaLabel="Show the evaluations list"
                dataAttr="evaluation-overview-card-attention"
            />
            <Tile
                {...shared}
                title="Pass rate"
                value={passRates?.median ?? undefined}
                formatValue={formatPercent}
                data={toChartValues(passRates?.medianTrend ?? [])}
                change={medianChange !== null ? { value: medianChange } : null}
                formatChange={formatPoints}
                goodDirection="up"
                changeTooltip="Change in the median against the previous period, for evaluations with results in both"
                restingSubtitle={counted.length === 1 ? counted[0].name : `Median of ${counted.length} evaluations`}
                // Entries without a median all have too few graded results to count.
                emptyMessage={
                    passRates?.entries.length
                        ? 'Too few graded results yet'
                        : 'No evaluation with a pass rate has results yet'
                }
                selected={metric === 'pass_rate'}
                onClick={() => selectCard('pass_rate')}
                ariaLabel="Show pass rate over time"
                dataAttr="evaluation-overview-card-pass-rate"
            />
            <Tile
                {...shared}
                title="Graded results"
                value={totals && totals.graded > 0 ? totals.graded : undefined}
                formatValue={humanFriendlyNumber}
                emptyMessage="No graded results in this range"
                data={totals?.gradedTrend ?? []}
                change={gradedChange !== null ? { value: gradedChange } : null}
                positiveColor={neutral}
                negativeColor={neutral}
                changeTooltip="Change against the previous period, for evaluations with results in both"
                restingSubtitle={`In ${pluralize(periodLength, interval)}`}
                selected={metric === 'graded'}
                onClick={() => selectCard('graded')}
                ariaLabel="Show graded results over time"
                dataAttr="evaluation-overview-card-graded"
            />
            {hasSentimentEvaluation && (
                <Tile
                    {...shared}
                    title="Negative sentiment"
                    value={sentiment?.negativeShare}
                    formatValue={(value) => `${Math.round(value)}%`}
                    data={toChartValues(sentimentRow?.trend.values ?? [])}
                    change={
                        sentiment && sentiment.previousShare !== null
                            ? { value: sentiment.negativeShare - sentiment.previousShare }
                            : null
                    }
                    formatChange={formatPoints}
                    goodDirection="down"
                    changeTooltip="Change in the share of negative user messages against the previous period"
                    restingSubtitle="of last user messages"
                    emptyMessage="No messages classified in this range"
                    selected={metric === 'sentiment'}
                    onClick={() => selectCard('sentiment')}
                    ariaLabel="Show negative sentiment over time"
                    dataAttr="evaluation-overview-card-sentiment"
                />
            )}
        </div>
    )
}
