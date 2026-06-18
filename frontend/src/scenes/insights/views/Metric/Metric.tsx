import clsx from 'clsx'
import { useValues } from 'kea'

import { MetricCard, type MetricChange, useChartTheme } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { formatDate, hexToRGBA } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'

// Above this magnitude the exact percentage is noise (it comes from a near-zero prior), so show ∞ instead.
const MAX_CHANGE_PERCENT = 10_000 // ≈100×

// Defaults for "color line by trend" — mirror MetricCard's default pill colors (green good, red bad).
export const METRIC_DEFAULT_GOOD_COLOR = '#388600'
export const METRIC_DEFAULT_BAD_COLOR = '#db3707'

export function Metric({ showPersonsModal = true, inCardView, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, compareFilter, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { baseCurrency } = useValues(teamLogic)
    const theme = useChartTheme()

    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    if (!resultSeries) {
        return <InsightEmptyState />
    }

    // The Metric headline is the metric over the period (the series total); the sparkline shows its movement.
    const headlineValue = resultSeries.count

    const goodDirection = trendsFilter?.metricGoodDirection ?? 'up'
    const showChange = trendsFilter?.metricShowChange ?? true

    // Metric always compares to the previous period (compare is forced on when the display is selected), so the
    // pill and subtitle reflect period-over-period change.
    const showComparison = !!compareFilter?.compare && (insightData?.result?.length ?? 0) > 1
    const previousValue = showComparison ? (insightData?.result?.[1] as TrendResult | undefined)?.count : undefined
    // Without a comparison, leave `change` undefined so MetricCard derives the pill from the sparkline. When
    // comparing, show the period-over-period %; but a change from a zero prior is infinite and a near-zero prior
    // produces an absurd number, so render ∞ in those cases (the `value` still drives the arrow + color).
    let change: MetricChange | null | undefined = undefined
    if (showComparison && previousValue != null && headlineValue != null) {
        if (previousValue === 0) {
            change = headlineValue > 0 ? { value: 1, label: '∞' } : null
        } else {
            const percent = ((headlineValue - previousValue) / Math.abs(previousValue)) * 100
            change = Math.abs(percent) >= MAX_CHANGE_PERCENT ? { value: percent, label: '∞' } : { value: percent }
        }
    }
    const comparisonSubtitle =
        showComparison && previousValue != null
            ? `vs. ${formatAggregationAxisValue(trendsFilter, previousValue, baseCurrency)} prior`
            : undefined

    // Optional: color the line + pill by whether the trend is good or bad (else the line uses the theme color and
    // the pill uses MetricCard's green/red defaults). `isGood` mirrors MetricCard's own pill logic.
    const colorByDirection = trendsFilter?.metricColorByDirection ?? false
    const goodColor = trendsFilter?.metricGoodColor ?? METRIC_DEFAULT_GOOD_COLOR
    const badColor = trendsFilter?.metricBadColor ?? METRIC_DEFAULT_BAD_COLOR
    const isGood = goodDirection === 'up' ? (change?.value ?? 0) >= 0 : (change?.value ?? 0) < 0
    const lineColor = colorByDirection && change != null ? (isGood ? goodColor : badColor) : undefined
    const pillColors = colorByDirection
        ? {
              positiveColor: { background: hexToRGBA(goodColor, 0.1), foreground: goodColor },
              negativeColor: { background: hexToRGBA(badColor, 0.1), foreground: badColor },
          }
        : {}

    // Sparkline hover/resting subtitle (used when there's no comparison) is the point's date — format it the app's
    // way ("June 16, 2026") rather than the raw backend label ("16-Jun-2026").
    const labels = resultSeries.days?.map((day) => formatDate(dayjs(day))) ?? resultSeries.labels

    const handleClick = context?.onDataPointClick
        ? () => context?.onDataPointClick?.({ compare: 'current' }, resultSeries)
        : showPersonsModal && headlineValue != null && !hasDataWarehouseSeries // != is intentional to catch undefined too
          ? () => {
                openPersonsModal({
                    title: resultSeries.label,
                    query: {
                        kind: NodeKind.InsightActorsQuery,
                        source: querySource!,
                        compare: showComparison ? 'current' : undefined,
                        includeRecordings: true,
                    },
                    additionalSelect: {
                        value_at_data_point: 'event_count',
                        matched_recordings: 'matched_recordings',
                    },
                    orderBy: ['event_count DESC, actor_id DESC'],
                })
            }
          : undefined

    // Left-aligned, full-width tile. On a dashboard card the content fills the height (value/pill at the top,
    // sparkline grows to fill the rest); in the insight view the tile is content-height at the top.
    return (
        <div className={clsx('Metric ph-no-capture flex flex-col w-full p-4', inCardView && 'flex-1')}>
            <MetricCard
                // Fill the card height so the sparkline can grow into the remaining space.
                className={inCardView ? 'flex-1' : undefined}
                sparklineFill={inCardView}
                // No title (the insight/card header already shows the name); the change pill renders inline on the
                // value's row.
                title={null}
                value={headlineValue}
                changeSize="md"
                changeInline
                change={change}
                {...pillColors}
                subtitle={comparisonSubtitle}
                data={resultSeries.data}
                labels={labels}
                theme={theme}
                color={lineColor}
                goodDirection={goodDirection}
                showChange={showChange}
                formatValue={(value) => formatAggregationAxisValue(trendsFilter, value, baseCurrency)}
                sparklineHeight={120}
                // Bleed the sparkline to the left/right edges; keep it directly under the value.
                sparklineClassName="mt-4 -mx-4"
                headline={(formattedValue) => (
                    <div
                        className={clsx(
                            'text-4xl font-bold tracking-tight tabular-nums',
                            showPersonsModal ? 'cursor-pointer' : 'cursor-default'
                        )}
                        data-attr="bold-number-value"
                        onClick={handleClick}
                    >
                        {formattedValue}
                    </div>
                )}
            />
        </div>
    )
}
