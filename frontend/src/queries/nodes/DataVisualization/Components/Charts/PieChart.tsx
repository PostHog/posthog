import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonColorGlyph } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { PieChart as InsightPieChart } from 'scenes/insights/views/LineGraph/PieChart'

import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType, GraphType, InsightLogicProps } from '~/types'

import { AxisSeries, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import { SqlPieGraph } from './SqlPieGraph'
import { buildPieSlices, canRenderSqlPieGraph, formatPieSliceCount } from './sqlPieGraphAdapter'

export interface PieChartProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
    uniqueKey: string
}

export function PieChart(props: PieChartProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const newChartsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS]

    const sqlPieProps: LineGraphProps = {
        xData: props.xData,
        yData: props.yData,
        visualizationType: ChartDisplayType.ActionsPie,
        chartSettings: props.chartSettings,
        presetChartHeight: props.presetChartHeight,
        className: props.className,
    }

    if (newChartsEnabled && canRenderSqlPieGraph(sqlPieProps)) {
        return <SqlPieGraph {...sqlPieProps} />
    }

    return <LegacyPieChart {...props} />
}

function LegacyPieChart({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
    uniqueKey,
}: PieChartProps): JSX.Element {
    const insightProps = useMemo<InsightLogicProps>(
        () => ({
            dashboardItemId: `new-sql-pie-chart-${uniqueKey}`,
        }),
        [uniqueKey]
    )

    const slices = useMemo(() => buildPieSlices(xData, yData), [xData, yData])
    const formattingSettings = yData[0]?.settings
    const total = slices.reduce((sum, slice) => sum + slice.value, 0)
    const showLegend = chartSettings.showLegend ?? false
    // Unset means an existing chart from before the labels option — keep showing values. New pies
    // are stamped with 'labels' when the type is picked (see dataVisualizationLogic).
    const sliceContent = chartSettings.pie?.sliceContent ?? 'values'
    // The total is a sum-of-values readout, so default it on only when slices show values.
    // `showPieTotal` is the legacy top-level toggle — honor it for charts saved before `pie`.
    const showPieTotal = chartSettings.pie?.showTotal ?? chartSettings.showPieTotal ?? sliceContent === 'values'
    const asPercent = (chartSettings.pie?.valueDisplay ?? 'absolute') === 'percentage'

    const absoluteFormatter = (value: number): string =>
        String(formatDataWithSettings(value, formattingSettings) ?? value)
    const sliceFormatter = (value: number): string =>
        asPercent ? (total > 0 ? `${parseFloat(((value / total) * 100).toFixed(1))}%` : '0%') : absoluteFormatter(value)

    // The legacy chart.js instance only rebuilds when its `useChart` deps change, and those exclude
    // the value formatter — so remount it when the slice content or absolute/percentage mode changes,
    // otherwise toggling them leaves the on-slice labels stale (only the React legend updates).
    const chartKey = `${JSON.stringify(formattingSettings?.formatting ?? {})}-${sliceContent}-${asPercent}`

    if (!slices.length) {
        return (
            <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
                <span className="text-secondary text-sm">Pie charts require at least one positive value.</span>
            </div>
        )
    }

    const chart = (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightPieChart
                key={chartKey}
                data-attr="sql-pie-chart"
                type={GraphType.Pie}
                labelGroupType="none"
                formula="-"
                showPersonsModal={false}
                tooltip={{
                    showHeader: false,
                    hideColorCol: true,
                    renderCount: (value: number) => formatPieSliceCount(value, total, formattingSettings, asPercent),
                }}
                datasets={[
                    {
                        id: 0,
                        data: slices.map((slice) => slice.value),
                        labels: slices.map((slice) => slice.label),
                        backgroundColor: slices.map((slice) => slice.color),
                        borderColor: slices.map((slice) => slice.color),
                    },
                ]}
                labels={slices.map((slice) => slice.label)}
                showValuesOnSeries={sliceContent === 'values'}
                showLabelOnSeries={sliceContent === 'labels'}
                valueFormatter={sliceFormatter}
            />
        </BindLogic>
    )

    const totalDisplay = showPieTotal ? (
        <div className="pt-4 text-center shrink-0">
            <div className="text-5xl font-bold">{absoluteFormatter(total)}</div>
        </div>
    ) : null

    const legend = showLegend ? (
        <div className="w-full xl:w-80 shrink-0 border border-border rounded bg-surface-secondary overflow-visible xl:overflow-auto">
            <div className="divide-y divide-border">
                {slices.map((slice) => {
                    const percent = total > 0 ? ((slice.value / total) * 100).toFixed(1) : '0.0'

                    return (
                        <div key={slice.label} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                            <div className="flex items-center gap-2 min-w-0">
                                <LemonColorGlyph color={slice.color} className="shrink-0" />
                                <span className="truncate">{slice.label}</span>
                            </div>
                            <div className="text-right shrink-0">
                                <div className="font-semibold">
                                    {asPercent ? `${percent}%` : absoluteFormatter(slice.value)}
                                </div>
                                <div className="text-xs text-secondary">
                                    {asPercent ? absoluteFormatter(slice.value) : `${percent}%`}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    ) : null

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary flex flex-1 p-4 gap-4', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            {!showLegend ? (
                <div className="flex flex-1 min-h-0">
                    <div className="flex flex-1 flex-col min-h-0">
                        <div className="relative flex-1 min-h-[18rem]">{chart}</div>
                        {totalDisplay}
                    </div>
                </div>
            ) : (
                <>
                    <div className="flex flex-col gap-4 w-full xl:hidden">
                        <div className="flex flex-col">
                            <div className="relative h-[18rem]">{chart}</div>
                            {totalDisplay}
                        </div>
                        {legend}
                    </div>
                    <div className="hidden xl:flex flex-1 gap-4 min-h-0">
                        <div className="flex flex-1 flex-col min-h-0">
                            <div className="relative flex-1 min-h-[18rem]">{chart}</div>
                            {totalDisplay}
                        </div>
                        {legend}
                    </div>
                </>
            )}
        </div>
    )
}
