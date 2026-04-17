import clsx from 'clsx'
import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { LemonColorGlyph } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { insightLogic } from 'scenes/insights/insightLogic'
import { PieChart as InsightPieChart } from 'scenes/insights/views/LineGraph/PieChart'

import { ChartSettings } from '~/queries/schema/schema-general'
import { InsightLogicProps, GraphType } from '~/types'

import { AxisSeries, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'

export interface PieChartProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
    uniqueKey: string
}

export interface PieSlice {
    label: string
    value: number
    color: string
}

const isBreakdownSeries = (
    series: AxisSeries<number | null> | AxisBreakdownSeries<number | null>
): series is AxisBreakdownSeries<number | null> => {
    return !('column' in series)
}

const toSliceLabel = (value: unknown): string => {
    if (value === null || value === undefined || value === '') {
        return '[No value]'
    }

    return String(value)
}

const sumValues = (values: (number | null)[]): number => {
    return values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
}

const getSeriesLabel = (
    series: AxisSeries<number | null> | AxisBreakdownSeries<number | null>,
    index: number
): string => {
    if (isBreakdownSeries(series)) {
        return series.name || `[Series ${index + 1}]`
    }

    return series.settings?.display?.label || series.column.name
}

export const buildPieSlices = (
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
): PieSlice[] => {
    if (!yData.length) {
        return []
    }

    if (yData.some(isBreakdownSeries)) {
        return yData
            .map((series, index) => ({
                label: getSeriesLabel(series, index),
                value: sumValues(series.data),
                color: series.settings?.display?.color ?? getSeriesColor(index),
            }))
            .filter((slice) => slice.value > 0)
    }

    if (yData.length === 1 && xData && xData.column.name !== 'None') {
        const totalsByLabel = new Map<string, number>()

        xData.data.forEach((rawLabel, index) => {
            const label = toSliceLabel(rawLabel)
            const value = yData[0].data[index] ?? 0
            totalsByLabel.set(label, (totalsByLabel.get(label) ?? 0) + value)
        })

        return Array.from(totalsByLabel.entries())
            .map(([label, value], index) => ({
                label,
                value,
                color: getSeriesColor(index),
            }))
            .filter((slice) => slice.value > 0)
    }

    return yData
        .map((series, index) => ({
            label: getSeriesLabel(series, index),
            value: sumValues(series.data),
            color: series.settings?.display?.color ?? getSeriesColor(index),
        }))
        .filter((slice) => slice.value > 0)
}

export function PieChart({
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
    const formattingKey = JSON.stringify(formattingSettings?.formatting ?? {})
    const total = slices.reduce((sum, slice) => sum + slice.value, 0)
    const showLegend = chartSettings.showLegend ?? false
    const showPieTotal = chartSettings.showPieTotal ?? true

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
                key={formattingKey}
                data-attr="sql-pie-chart"
                type={GraphType.Pie}
                labelGroupType="none"
                formula="-"
                showPersonsModal={false}
                tooltip={{
                    showHeader: false,
                    hideColorCol: true,
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
                showValuesOnSeries={chartSettings.showValuesOnSeries ?? true}
                valueFormatter={(value) => String(formatDataWithSettings(value, formattingSettings) ?? value)}
            />
        </BindLogic>
    )

    const totalDisplay = showPieTotal ? (
        <div className="pt-4 text-center shrink-0">
            <div className="text-5xl font-bold">
                {String(formatDataWithSettings(total, formattingSettings) ?? total)}
            </div>
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
                                    {String(formatDataWithSettings(slice.value, formattingSettings) ?? slice.value)}
                                </div>
                                <div className="text-xs text-secondary">{percent}%</div>
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
