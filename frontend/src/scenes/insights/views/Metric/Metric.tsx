import clsx from 'clsx'
import { useValues } from 'kea'

import { MetricCard, useChartTheme } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { hexToRGBA } from 'lib/utils/colors'
import { DATE_FORMAT_WITHOUT_YEAR, formatDate } from 'lib/utils/datetime'
import {
    defaultAggregationAxisFormatForDisplay,
    formatAggregationAxisValue,
} from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartDisplayType, ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'
import {
    computeMetricSummary,
    computeMetricSummaryChange,
    getMetricChangeTooltip,
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
    METRIC_SUMMARY_LABELS,
    selectCurrentSeries,
    selectPreviousSeriesSummary,
} from './Metric.utils'

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export function Metric({ inCardView }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, interval } = useValues(insightVizDataLogic(insightProps))
    const { incompletenessOffsetFromEnd } = useValues(trendsDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)
    const theme = useChartTheme()

    const results = insightData?.result as TrendResult[] | undefined
    const resultSeries = selectCurrentSeries(results)

    // `count` is typed as a number but can be absent at runtime, which would render a blank tile.
    if (!resultSeries || resultSeries.count == null) {
        return <InsightEmptyState />
    }

    const summary = trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT
    const headlineValue = computeMetricSummary(summary, resultSeries.count, resultSeries.data)
    const showChange = trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT

    const previousSeries = selectPreviousSeriesSummary(results)
    const change = computeMetricSummaryChange(
        summary,
        { total: resultSeries.count, data: resultSeries.data },
        previousSeries
    )
    const changeTooltip = getMetricChangeTooltip(summary, previousSeries != null, interval)

    const isIncrease = (change?.value ?? 0) >= 0
    const pillColors = {
        positiveColor: makeChangeColor(trendsFilter?.metricChangeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR),
        negativeColor: makeChangeColor(trendsFilter?.metricChangeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR),
    }
    const lineIncreaseColor = trendsFilter?.metricLineIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR
    const lineDecreaseColor = trendsFilter?.metricLineDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR
    let lineColor: string | undefined
    if ((trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT) && change != null) {
        lineColor = isIncrease ? lineIncreaseColor : lineDecreaseColor
    }

    // Format the backend day labels the app's way, without the year ("June 16" rather than "16-Jun-2026").
    const labels =
        resultSeries.days?.map((day) => formatDate(dayjs(day), DATE_FORMAT_WITHOUT_YEAR)) ?? resultSeries.labels

    // Dash the trailing in-progress period, matching the line chart. The offset is negative from the end.
    const dashedFromIndex =
        incompletenessOffsetFromEnd < 0 ? resultSeries.data.length + incompletenessOffsetFromEnd : undefined

    const aggregationAxisFormat =
        trendsFilter?.aggregationAxisFormat ?? defaultAggregationAxisFormatForDisplay(ChartDisplayType.Metric)

    return (
        <div className={clsx('Metric ph-no-capture flex flex-col w-full p-2', inCardView && 'flex-1')}>
            <MetricCard
                className={inCardView ? 'flex-1' : undefined}
                sparklineFill={inCardView}
                // No title — the insight/card header already shows the name.
                title={null}
                value={headlineValue}
                changeSize="md"
                changeInline
                change={change}
                changeTooltip={changeTooltip}
                hoverChangeFromPreviousPoint
                {...pillColors}
                restingSubtitle={METRIC_SUMMARY_LABELS[summary]}
                data={resultSeries.data}
                labels={labels}
                theme={theme}
                color={lineColor}
                showChange={showChange}
                formatValue={(value) =>
                    formatAggregationAxisValue({ ...trendsFilter, aggregationAxisFormat }, value, baseCurrency)
                }
                sparklineDashedFromIndex={dashedFromIndex}
                sparklineHeight={120}
                sparklineClassName="mt-4 -mx-2"
                dataAttr="metric-value"
            />
        </div>
    )
}
