import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconRefresh } from '@posthog/icons'
import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Heading,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Text,
} from 'lib/ui/quill'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import type { DateMappingOption } from '~/types'

import { DataModelingUsageListEngine } from './generated/api.schemas'
import { MaterializationJobsTable } from './MaterializationJobsTable'
import { ModelsUsageByModelTable } from './ModelsUsageByModelTable'
import { MATERIALIZATION_ENGINE_LABELS, MaterializedViewOption, modelsUsageLogic } from './modelsUsageLogic'

const DATE_OPTIONS: DateMappingOption[] = [7, 30, 90].map((days) => ({
    key: `Last ${days} complete days`,
    values: [`-${days}d`],
    getFormattedDate: (date: dayjs.Dayjs): string =>
        `${date.subtract(days, 'day').format('MMM D, YYYY')} – ${date.subtract(1, 'day').format('MMM D, YYYY')}`,
    defaultInterval: 'day',
}))

const ALL_VIEWS: MaterializedViewOption = { id: 'all', name: 'All materialized views' }

function MetricTile({ title, value }: { title: string; value: string }): JSX.Element {
    return (
        <Card size="sm" className="min-w-0">
            <CardContent>
                <Text size="sm">{title}</Text>
                <Heading size="xl" render={<div />} className="mt-2 truncate font-bold tracking-tight tabular-nums">
                    {value}
                </Heading>
            </CardContent>
        </Card>
    )
}

export function ModelsUsageTab({
    savedQueryIdToNodeId,
}: {
    savedQueryIdToNodeId: Record<string, string>
}): JSX.Element {
    const {
        usage,
        usageLoading,
        failed,
        dateFrom,
        dateTo,
        chartLabels,
        chartSeries,
        jobsLoading,
        managedWarehouseEnabled,
        materializedViewOptions,
        selectedEngine,
        selectedSavedQueryId,
    } = useValues(modelsUsageLogic)
    const { refresh, setDateRange, loadUsage, setSelectedEngine, setSelectedSavedQueryId } =
        useActions(modelsUsageLogic)
    const viewFilterRef = useRef<HTMLButtonElement>(null)
    const viewOptions = useMemo(() => [ALL_VIEWS, ...materializedViewOptions], [materializedViewOptions])
    const selectedView = viewOptions.find((option) => option.id === (selectedSavedQueryId ?? ALL_VIEWS.id)) ?? ALL_VIEWS
    const theme = useChartTheme()
    const chartConfig = useChartConfig(
        () => ({
            yAxis: { showGrid: true, tickFormatter: (value: number) => humanizeBytes(value) },
            xAxis: { timezone: 'UTC', interval: 'day' as const },
            tooltip: { valueFormatter: (value: number) => humanizeBytes(value) },
            barLayout: 'stacked' as const,
            legend: { show: chartSeries.length > 1, position: 'top' as const, interactive: true },
        }),
        [chartSeries.length]
    )

    return (
        <div className="space-y-4" data-attr="models-usage" data-quill>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <Heading size="xl" render={<h2 />}>
                        Materialization usage
                    </Heading>
                    <Text variant="muted">Find the models and jobs that read the most data when they refresh.</Text>
                </div>
                <div className="flex flex-wrap gap-2">
                    <Combobox
                        items={viewOptions}
                        value={selectedView}
                        itemToStringValue={(option: MaterializedViewOption) => option.name}
                        isItemEqualToValue={(option, value) => option.id === value.id}
                        onValueChange={(option: MaterializedViewOption | null) =>
                            setSelectedSavedQueryId(!option || option.id === ALL_VIEWS.id ? null : option.id)
                        }
                    >
                        <ComboboxTrigger
                            ref={viewFilterRef}
                            render={<Button variant="outline" className="max-w-72 justify-between" />}
                            data-attr="models-usage-view-filter"
                            disabled={usageLoading || jobsLoading}
                        >
                            <span className="truncate">{selectedView.name}</span>
                        </ComboboxTrigger>
                        <ComboboxContent anchor={viewFilterRef} align="end" className="w-80 max-w-[calc(100vw-2rem)]">
                            <ComboboxInput placeholder="Search materialized views" showTrigger={false} />
                            <ComboboxEmpty>No materialized views found.</ComboboxEmpty>
                            <ComboboxList>
                                {(option: MaterializedViewOption) => (
                                    <ComboboxItem key={option.id} value={option} title={option.name}>
                                        <span className="truncate">{option.name}</span>
                                    </ComboboxItem>
                                )}
                            </ComboboxList>
                        </ComboboxContent>
                    </Combobox>
                    {managedWarehouseEnabled ? (
                        <Select
                            value={selectedEngine}
                            onValueChange={(value) => value && setSelectedEngine(value as DataModelingUsageListEngine)}
                        >
                            <SelectTrigger
                                data-attr="models-usage-engine-filter"
                                disabled={usageLoading || jobsLoading}
                            >
                                <SelectValue>
                                    {(value: DataModelingUsageListEngine) =>
                                        MATERIALIZATION_ENGINE_LABELS[value] ?? value
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent align="end" alignItemWithTrigger={false}>
                                <SelectItem value={DataModelingUsageListEngine.All}>All engines</SelectItem>
                                <SelectItem value={DataModelingUsageListEngine.Clickhouse}>ClickHouse</SelectItem>
                                <SelectItem value={DataModelingUsageListEngine.ManagedWarehouse}>
                                    Managed warehouse
                                </SelectItem>
                            </SelectContent>
                        </Select>
                    ) : null}
                    <div data-attr="models-usage-date-range">
                        <DateFilter
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={setDateRange}
                            dateOptions={DATE_OPTIONS}
                            showRollingRangePicker={false}
                            forceGranularity="day"
                            disabled={usageLoading || jobsLoading}
                        />
                    </div>
                    <Button
                        variant="outline"
                        onClick={refresh}
                        loading={usageLoading || jobsLoading}
                        data-attr="models-usage-refresh"
                    >
                        <IconRefresh />
                        Refresh
                    </Button>
                </div>
            </div>
            <Text size="sm" variant="muted">
                Usage updates daily and excludes today. Job history starts on the selected start date and includes
                current jobs. All dates are UTC. Usage includes failed runs, canceled runs, schema checks, and retries.
            </Text>

            {failed ? (
                <Card size="sm" className="border-destructive">
                    <CardContent className="flex flex-wrap items-center justify-between gap-3">
                        <Text>Could not load model usage. Try again, or contact support if this continues.</Text>
                        <Button variant="outline" onClick={() => loadUsage()} loading={usageLoading}>
                            Try again
                        </Button>
                    </CardContent>
                </Card>
            ) : !usage || usageLoading ? (
                <div className="flex justify-center py-16">
                    <Spinner />
                </div>
            ) : usage.overview.runs === 0 ? (
                <Card size="sm">
                    <CardContent>
                        <Text variant="muted">
                            No materialization runs match these filters. Choose a longer date range or change a filter.
                        </Text>
                    </CardContent>
                </Card>
            ) : (
                <>
                    {usage.overview.measured_runs < usage.overview.runs ? (
                        <Card size="sm">
                            <CardContent>
                                <Text variant="muted">
                                    {humanFriendlyNumber(usage.overview.measured_runs)} of{' '}
                                    {humanFriendlyNumber(usage.overview.runs)} runs have measured usage. Totals include
                                    measured runs only. Recent runs appear after the next daily update; older runs may
                                    be unavailable.
                                </Text>
                            </CardContent>
                        </Card>
                    ) : null}
                    <div className="grid grid-cols-1 gap-4 @min-[36rem]/main-content:grid-cols-3">
                        <MetricTile
                            title="Bytes read"
                            value={
                                usage.overview.read_bytes === null
                                    ? 'Not measured'
                                    : humanizeBytes(usage.overview.read_bytes)
                            }
                        />
                        <MetricTile
                            title="CPU time"
                            value={
                                usage.overview.cpu_microseconds === null
                                    ? 'Not measured'
                                    : humanFriendlyDuration(usage.overview.cpu_microseconds / 1_000_000)
                            }
                        />
                        <MetricTile title="Runs" value={humanFriendlyNumber(usage.overview.runs)} />
                    </div>
                    {usage.overview.measured_runs > 0 ? (
                        <Card size="sm" className="min-w-0">
                            <CardHeader>
                                <CardTitle role="heading" aria-level={3}>
                                    Bytes read by day
                                </CardTitle>
                                <CardDescription>
                                    Usage is attributed to the day each run finished. Gaps have no measured usage.
                                    {chartSeries.length > 1 ? ' Bars are stacked by engine.' : ''}
                                </CardDescription>
                            </CardHeader>
                            <CardContent>
                                <div className="h-64 flex flex-col">
                                    <TimeSeriesBarChart
                                        series={chartSeries}
                                        labels={chartLabels}
                                        theme={theme}
                                        config={chartConfig}
                                    />
                                </div>
                            </CardContent>
                        </Card>
                    ) : null}
                    <ModelsUsageByModelTable savedQueryIdToNodeId={savedQueryIdToNodeId} />
                </>
            )}

            <MaterializationJobsTable savedQueryIdToNodeId={savedQueryIdToNodeId} />
        </div>
    )
}
