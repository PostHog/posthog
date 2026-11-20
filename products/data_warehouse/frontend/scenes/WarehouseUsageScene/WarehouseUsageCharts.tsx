import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Text,
} from '@posthog/quill'
import {
    ReferenceLine,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type Series,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'

import { chartByteUnit, formatAxisBytes, formatBytes } from '../WarehouseConsole/warehouseConsoleFormat'
import { warehouseUsageLogic } from './warehouseUsageLogic'

const X_AXIS = { timezone: 'UTC', interval: 'day' } as const

export function WarehouseUsageCharts(): JSX.Element | null {
    const { usage, chartData, freeAllowanceCrossingDate } = useValues(warehouseUsageLogic)
    const theme = useChartTheme()

    // The axes count in one binary unit, so their ticks are round numbers in it (0, 100, 200 GiB).
    const scannedUnit = useMemo(() => chartByteUnit(Math.max(0, ...chartData.billableBytes)), [chartData.billableBytes])
    const storageUnit = useMemo(
        () => chartByteUnit(Math.max(0, ...chartData.storageAverageBytes)),
        [chartData.storageAverageBytes]
    )
    const scannedSeries = useMemo<Series[]>(
        () => [
            {
                key: 'billable',
                label: 'Billable scanned',
                data: chartData.billableBytes.map((bytes) => bytes / scannedUnit.divisor),
            },
        ],
        [chartData.billableBytes, scannedUnit]
    )
    const storageSeries = useMemo<Series[]>(
        () => [
            {
                key: 'storage',
                label: 'Average stored',
                data: chartData.storageAverageBytes.map((bytes) => bytes / storageUnit.divisor),
            },
        ],
        [chartData.storageAverageBytes, storageUnit]
    )

    const scannedConfig = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            xAxis: X_AXIS,
            yAxis: { tickFormatter: (value: number) => formatAxisBytes(value, scannedUnit), startAtZero: true },
            tooltip: { valueFormatter: (value: number) => formatBytes(value * scannedUnit.divisor) },
        }),
        [scannedUnit]
    )
    const storageConfig = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: X_AXIS,
            yAxis: { tickFormatter: (value: number) => formatAxisBytes(value, storageUnit), startAtZero: true },
            tooltip: { valueFormatter: (value: number) => formatBytes(value * storageUnit.divisor) },
        }),
        [storageUnit]
    )

    if (!usage) {
        return null
    }
    if (chartData.labels.length === 0) {
        return (
            <Card>
                <CardContent>
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No usage yet</EmptyTitle>
                            <EmptyDescription>Daily usage appears here after your first queries.</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                </CardContent>
            </Card>
        )
    }

    return (
        <div className="grid grid-cols-1 gap-3 @3xl/warehouse-usage:grid-cols-2">
            <Card data-attr="warehouse-usage-scanned-chart">
                <CardHeader>
                    <CardTitle>Billable data scanned per day</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                    <div className="flex h-56 w-full flex-col">
                        <TimeSeriesBarChart
                            series={scannedSeries}
                            labels={chartData.labels}
                            theme={theme}
                            config={scannedConfig}
                        >
                            {freeAllowanceCrossingDate ? (
                                <ReferenceLine
                                    value={freeAllowanceCrossingDate}
                                    orientation="vertical"
                                    variant="alert"
                                />
                            ) : null}
                        </TimeSeriesBarChart>
                    </div>
                    {freeAllowanceCrossingDate ? (
                        <Text size="xs" variant="muted">
                            The running total passed the free {formatBytes(usage.compute.free_bytes)} on{' '}
                            {dayjs.utc(freeAllowanceCrossingDate).format('MMM D')}.
                        </Text>
                    ) : null}
                </CardContent>
            </Card>
            <Card data-attr="warehouse-usage-storage-chart">
                <CardHeader>
                    <CardTitle>Average stored per day</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex h-56 w-full flex-col">
                        <TimeSeriesLineChart
                            series={storageSeries}
                            labels={chartData.labels}
                            theme={theme}
                            config={storageConfig}
                        />
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}
