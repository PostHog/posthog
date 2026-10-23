import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
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

import { MaterializationJobsTable } from './MaterializationJobsTable'
import { ModelsUsageByModelTable } from './ModelsUsageByModelTable'
import { modelsUsageLogic } from './modelsUsageLogic'

const DATE_RANGE_LABELS: Record<string, string> = {
    '7': 'Last 7 complete days',
    '30': 'Last 30 complete days',
    '90': 'Last 90 complete days',
}

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

export function ModelsUsageTab(): JSX.Element {
    const { usage, usageLoading, failed, days, chartLabels, chartSeries, jobsLoading } = useValues(modelsUsageLogic)
    const { refresh, setDays, loadUsage } = useActions(modelsUsageLogic)
    const theme = useChartTheme()
    const chartConfig = useChartConfig(
        () => ({
            yAxis: { showGrid: true, tickFormatter: (value: number) => humanizeBytes(value) },
            xAxis: { timezone: 'UTC', interval: 'day' as const },
            tooltip: { valueFormatter: (value: number) => humanizeBytes(value) },
        }),
        []
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
                    <Select value={String(days)} onValueChange={(value) => value && setDays(Number(value))}>
                        <SelectTrigger data-attr="models-usage-date-range" disabled={usageLoading}>
                            <SelectValue>{(value: string) => DATE_RANGE_LABELS[value] ?? value}</SelectValue>
                        </SelectTrigger>
                        <SelectContent align="end" alignItemWithTrigger={false}>
                            <SelectItem value="7">Last 7 complete days</SelectItem>
                            <SelectItem value="30">Last 30 complete days</SelectItem>
                            <SelectItem value="90">Last 90 complete days</SelectItem>
                        </SelectContent>
                    </Select>
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
                Usage updates daily and excludes today. All dates are UTC. Includes failed runs, canceled runs, schema
                checks, and retries.
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
                            No ClickHouse materialization runs finished in this period. Choose a longer date range or
                            materialize a model to see its usage.
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
                    <ModelsUsageByModelTable />
                </>
            )}

            <MaterializationJobsTable />
        </div>
    )
}
