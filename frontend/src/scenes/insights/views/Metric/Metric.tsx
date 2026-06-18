import clsx from 'clsx'
import { useValues } from 'kea'

import { MetricCard, useChartTheme } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { formatDate, hexToRGBA } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'
import {
    computeMetricChange,
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
} from './Metric.utils'

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export function Metric({ inCardView }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)
    const theme = useChartTheme()

    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    // `count` is typed as a number but can be absent at runtime, which would render a blank tile.
    if (!resultSeries || resultSeries.count == null) {
        return <InsightEmptyState />
    }

    const headlineValue = resultSeries.count
    const showChange = trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT

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
    if ((trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT) && change != null) {
        lineColor = isIncrease ? lineIncreaseColor : lineDecreaseColor
    }

    // Format the backend day labels the app's way ("June 16, 2026" rather than "16-Jun-2026").
    const labels = resultSeries.days?.map((day) => formatDate(dayjs(day))) ?? resultSeries.labels

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
                dataAttr="metric-value"
            />
        </div>
    )
}
