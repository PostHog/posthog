import { useMemo } from 'react'

import { LemonLabel, LemonSkeleton, SpinnerOverlay } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export type AppMetricSummaryProps = {
    name: string
    description: string
    color?: string
    colorIfZero?: string
    timeSeries: AppMetricsTimeSeriesResponse | null
    previousPeriodTimeSeries?: AppMetricsTimeSeriesResponse | null
    loading?: boolean
}

export function AppMetricSummary({
    name,
    timeSeries,
    previousPeriodTimeSeries,
    description,
    color,
    colorIfZero,
    loading,
}: AppMetricSummaryProps): JSX.Element {
    const total = useMemo(() => {
        if (!timeSeries) {
            return 0
        }
        return timeSeries.series.reduce((acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0), 0)
    }, [timeSeries])

    const totalPreviousPeriod = useMemo(() => {
        if (!previousPeriodTimeSeries) {
            return 0
        }
        return previousPeriodTimeSeries.series.reduce(
            (acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0),
            0
        )
    }, [previousPeriodTimeSeries])

    const diff = (total - totalPreviousPeriod) / totalPreviousPeriod

    return (
        <div className="flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]">
            <div className="flex flex-row justify-between items-start">
                <LemonLabel info={description}>{name}</LemonLabel>
                {loading ? (
                    <LemonSkeleton className="w-20 h-6 mb-2" />
                ) : (
                    <div className="text-right text-2xl text-muted-foreground">{humanFriendlyNumber(total)}</div>
                )}
            </div>
            <div className="flex flex-row justify-end items-center gap-2 text-xs text-muted">
                {loading ? (
                    <LemonSkeleton className="w-10 h-4" />
                ) : (
                    <>{diff > 0 ? ` (+${(diff * 100).toFixed(1)}%)` : ` (-${(-diff * 100).toFixed(1)}%)`}</>
                )}
            </div>

            <div className="flex-1 mt-2">
                <div className="h-[10rem]">
                    {loading ? (
                        <SpinnerOverlay />
                    ) : !timeSeries ? (
                        <div className="flex-1 flex items-center justify-center">
                            <LemonLabel>No data</LemonLabel>
                        </div>
                    ) : (
                        <LineGraph
                            xData={{
                                column: {
                                    name: 'date',
                                    type: {
                                        name: 'DATE',
                                        isNumerical: false,
                                    },
                                    label: 'Date',
                                    dataIndex: 0,
                                },
                                data: timeSeries.labels,
                            }}
                            yData={timeSeries.series.map((x) => ({
                                column: {
                                    name: x.name,
                                    type: { name: 'INTEGER', isNumerical: true },
                                    label: x.name,
                                    dataIndex: 0,
                                },
                                data: x.values,
                                settings: {
                                    display: {
                                        color: total === 0 ? colorIfZero : color,
                                    },
                                },
                            }))}
                            visualizationType={ChartDisplayType.ActionsLineGraph}
                            chartSettings={{
                                showLegend: false,
                                showTotalRow: false,
                                showXAxisBorder: false,
                                showYAxisBorder: false,
                                showXAxisTicks: false,
                                leftYAxisSettings: {
                                    showTicks: false,
                                    showGridLines: false,
                                },
                            }}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
