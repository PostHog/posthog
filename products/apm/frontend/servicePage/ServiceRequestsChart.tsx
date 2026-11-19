import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'
import { DefaultTooltip, type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { TRACING_DATE_TIME_FORMAT, TRACING_DISPLAY_TIMEZONE } from 'products/tracing/frontend/dateFormats'

import { bucketIntervalLabel, type RequestsSeries } from './servicePage'

export interface ServiceRequestsChartProps {
    data: RequestsSeries | null
    loading: boolean
}

export function ServiceRequestsChart({ data, loading }: ServiceRequestsChartProps): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () =>
            data
                ? [
                      { key: 'ok', label: 'Successful', data: data.requests, color: getColorVar('data-color-1') },
                      { key: 'errors', label: 'Errors', data: data.errors, color: getColorVar('danger') },
                  ]
                : [],
        [data]
    )
    const interval = data ? bucketIntervalLabel(data.times) : null
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: { timezone: TRACING_DISPLAY_TIMEZONE },
            yAxis: { label: interval ? `Requests / ${interval}` : 'Requests' },
            showGrid: true,
            legend: { show: true, position: 'bottom', align: 'start' },
        }),
        [interval]
    )
    const hasData = !!data && data.times.length > 0

    return (
        // Quill's chart root is flex-1, so the sized container has to be a flex column.
        <div className="relative h-56 flex flex-col" data-attr="apm-service-requests-chart">
            {hasData ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={data.times}
                    theme={theme}
                    config={config}
                    tooltip={(ctx) => (
                        <DefaultTooltip
                            {...ctx}
                            valueFormatter={(value) => humanFriendlyNumber(value)}
                            labelFormatter={(label) =>
                                dayjs(label).tz(TRACING_DISPLAY_TIMEZONE).format(TRACING_DATE_TIME_FORMAT)
                            }
                        />
                    )}
                />
            ) : !loading ? (
                <div className="h-full text-muted text-xs flex items-center justify-center">
                    No requests in this window
                </div>
            ) : null}
            {loading && <SpinnerOverlay />}
        </div>
    )
}
