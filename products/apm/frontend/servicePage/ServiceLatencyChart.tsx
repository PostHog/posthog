import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'
import { DefaultTooltip, type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { TRACING_DATE_TIME_FORMAT, TRACING_DISPLAY_TIMEZONE } from 'products/tracing/frontend/dateFormats'

import { formatMs } from '../healthDisplay'
import type { LatencyPercentiles } from './servicePage'

const NS_PER_MS = 1_000_000

export interface ServiceLatencyChartProps {
    percentiles: LatencyPercentiles
    loading: boolean
}

export function ServiceLatencyChart({ percentiles, loading }: ServiceLatencyChartProps): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(() => {
        const toMs = (values: number[]): number[] => values.map((ns) => ns / NS_PER_MS)
        return [
            { key: 'p50', label: 'p50', data: toMs(percentiles.p50), color: getColorVar('data-color-1') },
            { key: 'p95', label: 'p95', data: toMs(percentiles.p95), color: getColorVar('data-color-3') },
            { key: 'p99', label: 'p99', data: toMs(percentiles.p99), color: getColorVar('data-color-4') },
        ]
    }, [percentiles])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone: TRACING_DISPLAY_TIMEZONE },
            yAxis: { format: 'duration_ms', showGrid: true },
            legend: { show: true, position: 'bottom', align: 'start' },
        }),
        []
    )

    return (
        <div className="relative h-56 flex flex-col" data-attr="apm-service-latency-chart">
            {percentiles.times.length > 0 ? (
                <TimeSeriesLineChart
                    series={series}
                    labels={percentiles.times}
                    theme={theme}
                    config={config}
                    tooltip={(ctx) => (
                        <DefaultTooltip
                            {...ctx}
                            valueFormatter={(value) => formatMs(value)}
                            labelFormatter={(label) =>
                                dayjs(label).tz(TRACING_DISPLAY_TIMEZONE).format(TRACING_DATE_TIME_FORMAT)
                            }
                        />
                    )}
                />
            ) : !loading ? (
                <div className="h-full text-muted text-xs flex items-center justify-center">
                    No spans in this window
                </div>
            ) : null}
            {loading && <SpinnerOverlay />}
        </div>
    )
}
