import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { ChartLegend, TimeSeriesBarChart, TimeSeriesLineChart, legendItemsFromSeries } from '@posthog/quill-charts'
import type {
    Series,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
    TooltipConfig,
    TooltipContext,
    YAxisConfig,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import type { TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'
import type { GraphDataset } from '~/types'

import { trendsFilterToYFormatterConfig } from 'products/product_analytics/frontend/insights/trends/shared/trendsAxisFormat'
import type { TrendsSeriesMeta } from 'products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta'
import { TrendsTooltip } from 'products/product_analytics/frontend/insights/trends/shared/TrendsTooltip'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

type MarketingChartKind = 'line' | 'area' | 'bar'

const DISPLAY_TYPE_TO_KIND: Partial<Record<ChartDisplayType, MarketingChartKind>> = {
    [ChartDisplayType.ActionsLineGraph]: 'line',
    [ChartDisplayType.ActionsAreaGraph]: 'area',
    [ChartDisplayType.ActionsBar]: 'bar',
}

function buildSeries(datasets: GraphDataset[], kind: MarketingChartKind): Series<TrendsSeriesMeta>[] {
    return datasets.map((dataset, index) => ({
        key: String(dataset.id ?? index),
        label: dataset.label ?? '',
        data: (dataset.data ?? []) as number[],
        fill: kind === 'area' ? {} : undefined,
        meta: {
            action: dataset.action,
            breakdown_value: dataset.breakdown_value,
            days: dataset.days,
            order: dataset.action?.order ?? index,
        },
    }))
}

export interface MarketingAnalyticsTrendsChartProps {
    dataAttr: string
    datasets: GraphDataset[]
    labels: string[]
    trendsFilter?: TrendsFilter | null
}

export function MarketingAnalyticsTrendsChart({
    dataAttr,
    datasets,
    labels,
    trendsFilter,
}: MarketingAnalyticsTrendsChartProps): JSX.Element {
    const { timezone, baseCurrency } = useValues(teamLogic)
    const { chartDisplayType, dateFilter } = useValues(marketingAnalyticsLogic)

    const theme = useChartTheme()
    const kind = DISPLAY_TYPE_TO_KIND[chartDisplayType] ?? 'bar'

    const series = useMemo(() => buildSeries(datasets, kind), [datasets, kind])

    const yAxis = useMemo<YAxisConfig>(
        () => ({ ...trendsFilterToYFormatterConfig(trendsFilter, false, baseCurrency), showGrid: true }),
        [trendsFilter, baseCurrency]
    )

    const legendItems = useMemo(() => legendItemsFromSeries(series, theme), [series, theme])

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => (
            <TrendsTooltip
                context={ctx}
                timezone={timezone}
                interval={dateFilter.interval}
                trendsFilter={trendsFilter}
                baseCurrency={baseCurrency}
                groupTypeLabel=""
            />
        ),
        [timezone, dateFilter.interval, trendsFilter, baseCurrency]
    )

    // No xAxis config: the backend ships pre-formatted period labels, so the time-axis date formatter is
    // intentionally left inert (it would otherwise re-format the labels itself).
    const barConfig = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({ yAxis, barLayout: 'stacked', tooltip: TOOLTIP_CONFIG }),
        [yAxis]
    )
    const lineConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({ yAxis, showCrosshair: true, tooltip: TOOLTIP_CONFIG }),
        [yAxis]
    )

    const showLegend = series.length > 1

    if (kind === 'bar') {
        return (
            <ChartLegend show={showLegend} items={legendItems} position="right" legendDataAttr={`${dataAttr}-legend`}>
                <TimeSeriesBarChart<TrendsSeriesMeta>
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={barConfig}
                    tooltip={renderTooltip}
                    className="BarGraph"
                    dataAttr={dataAttr}
                />
            </ChartLegend>
        )
    }

    return (
        <ChartLegend show={showLegend} items={legendItems} position="right" legendDataAttr={`${dataAttr}-legend`}>
            <TimeSeriesLineChart<TrendsSeriesMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={lineConfig}
                tooltip={renderTooltip}
                className="LineGraph"
                dataAttr={dataAttr}
            />
        </ChartLegend>
    )
}
