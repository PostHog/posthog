import { useValues } from 'kea'
import { useMemo } from 'react'

import { Text } from '@posthog/quill'
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
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
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
            <WarehouseSection title="Daily usage">
                <Text size="sm" variant="muted">
                    Daily usage appears here after your first queries.
                </Text>
            </WarehouseSection>
        )
    }

    return (
        <div className="grid grid-cols-1 gap-3 @3xl/warehouse-usage:grid-cols-2">
            <WarehouseSection
                title="Billable data scanned per day"
                description={
                    freeAllowanceCrossingDate
                        ? `Dashed line: passed the free ${formatBytes(usage.compute.free_bytes)} on ${dayjs.utc(freeAllowanceCrossingDate).format('MMM D')}`
                        : 'Billable bytes read by queries each day'
                }
                data-attr="warehouse-usage-scanned-chart"
            >
                <div className="flex h-56 w-full flex-col">
                    <TimeSeriesBarChart
                        series={scannedSeries}
                        labels={chartData.labels}
                        theme={theme}
                        config={scannedConfig}
                    >
                        {freeAllowanceCrossingDate ? (
                            <ReferenceLine value={freeAllowanceCrossingDate} orientation="vertical" variant="marker" />
                        ) : null}
                    </TimeSeriesBarChart>
                </div>
            </WarehouseSection>
            <WarehouseSection
                title="Average stored per day"
                description="Daily average of data in storage"
                data-attr="warehouse-usage-storage-chart"
            >
                <div className="flex h-56 w-full flex-col">
                    <TimeSeriesLineChart
                        series={storageSeries}
                        labels={chartData.labels}
                        theme={theme}
                        config={storageConfig}
                    />
                </div>
            </WarehouseSection>
        </div>
    )
}
