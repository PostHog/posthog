import clsx from 'clsx'
import { useValues } from 'kea'

import { MetricCard, useChartTheme } from '@posthog/quill-charts'

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
import { computeMetricChange } from './Metric.utils'

export const METRIC_DEFAULT_INCREASE_COLOR = '#388600'
export const METRIC_DEFAULT_DECREASE_COLOR = '#db3707'

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export function Metric({ showPersonsModal = true, inCardView, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { baseCurrency } = useValues(teamLogic)
    const theme = useChartTheme()

    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    if (!resultSeries) {
        return <InsightEmptyState />
    }

    const headlineValue = resultSeries.count
    const showChange = trendsFilter?.metricShowChange ?? true

    // The pill and line both read from `change` (change across the displayed period), so they always agree.
    const { change, startValue } = computeMetricChange(resultSeries.data)
    const comparisonSubtitle =
        startValue != null
            ? `vs. ${formatAggregationAxisValue(trendsFilter, startValue, baseCurrency)} at start`
            : undefined

    const isIncrease = (change?.value ?? 0) >= 0
    const pillColors = {
        positiveColor: makeChangeColor(trendsFilter?.metricChangeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR),
        negativeColor: makeChangeColor(trendsFilter?.metricChangeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR),
    }
    const lineIncreaseColor = trendsFilter?.metricLineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR
    const lineDecreaseColor = trendsFilter?.metricLineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR
    let lineColor: string | undefined
    if ((trendsFilter?.metricColorByDirection ?? false) && change != null) {
        lineColor = isIncrease ? lineIncreaseColor : lineDecreaseColor
    }

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
                className={inCardView ? 'flex-1' : undefined}
                sparklineFill={inCardView}
                // No title — the insight/card header already shows the name.
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
                showChange={showChange}
                formatValue={(value) => formatAggregationAxisValue(trendsFilter, value, baseCurrency)}
                sparklineHeight={120}
                sparklineClassName="mt-4 -mx-4"
                headline={(formattedValue) => (
                    <div
                        className={clsx(
                            'text-4xl font-bold tracking-tight tabular-nums',
                            showPersonsModal ? 'cursor-pointer' : 'cursor-default'
                        )}
                        data-attr="metric-value"
                        onClick={handleClick}
                    >
                        {formattedValue}
                    </div>
                )}
            />
        </div>
    )
}
