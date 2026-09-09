import clsx from 'clsx'

import { MetricCard } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import {
    METRIC_DEFAULT_DECREASE_COLOR,
    METRIC_DEFAULT_INCREASE_COLOR,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_LABELS,
} from 'lib/components/Metric/metricSummary'
import { hexToRGBA } from 'lib/utils/colors'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { MetricChartSettings } from '~/queries/schema/schema-general'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { AxisSeries } from '../../dataVisualizationLogic'
import { formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { useSqlMetricModel } from './useSqlMetricModel'

const handleChartError = makeChartErrorHandler('sql-metric-chart')

const makeChangeColor = (hex: string): { background: string; foreground: string } => ({
    background: hexToRGBA(hex, 0.1),
    foreground: hex,
})

export interface SqlMetricCardProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[]
    metricSettings?: MetricChartSettings
    presetChartHeight?: boolean
    className?: string
}

export const SqlMetricCard = ({
    xData,
    yData,
    metricSettings,
    presetChartHeight,
    className,
}: SqlMetricCardProps): JSX.Element => {
    const theme = useChartTheme()
    const model = useSqlMetricModel({ xData, yData, metricSettings })

    return (
        <div
            className={clsx(className, 'Metric ph-no-capture rounded bg-surface-primary flex flex-1 min-h-0 p-3', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            {model ? (
                <MetricCard
                    title={null}
                    value={model.headlineValue}
                    data={model.data}
                    labels={model.labels}
                    theme={theme}
                    color={model.lineColor}
                    change={model.change}
                    changeTooltip="Comparing the first point to the latest point."
                    showChange={metricSettings?.showChange ?? METRIC_SHOW_CHANGE_DEFAULT}
                    positiveColor={makeChangeColor(
                        metricSettings?.changeIncreaseColor ?? METRIC_DEFAULT_INCREASE_COLOR
                    )}
                    negativeColor={makeChangeColor(
                        metricSettings?.changeDecreaseColor ?? METRIC_DEFAULT_DECREASE_COLOR
                    )}
                    restingSubtitle={model.summary === 'latest' ? undefined : METRIC_SUMMARY_LABELS[model.summary]}
                    changeInline
                    hoverChangeFromPreviousPoint
                    sparklineFill
                    sparklineClassName="mt-4 -mx-3 -mb-3"
                    formatValue={(value) => formatSqlSeriesValue(value, model.series.settings)}
                    dataAttr="metric-value"
                    onError={handleChartError}
                />
            ) : (
                <InsightEmptyState sampleDataVariant="number" />
            )}
        </div>
    )
}
