import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanizeBytes } from 'lib/utils/numbers'

import { EXCEPTION_CODE_LABELS, queryPerformanceLogic } from './queryPerformanceLogic'

const TIMESERIES_RANGE_OPTIONS = [
    { label: '48h', hours: 48 },
    { label: '7d', hours: 168 },
    { label: '14d', hours: 336 },
    { label: '21d', hours: 504 },
]

function ChartCard({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <div className="text-xs text-muted mb-2">{title}</div>
            <div className="h-48">{children}</div>
        </div>
    )
}

export function PrecomputeTrends(): JSX.Element {
    const { precomputeTimeseries, precomputeTimeseriesLoading, timeseriesHoursBack } = useValues(queryPerformanceLogic)
    const { setTimeseriesHoursBack } = useActions(queryPerformanceLogic)
    const theme = useChartTheme()

    const ts = precomputeTimeseries
    const xAxis = ts ? { timezone: 'UTC', interval: ts.interval } : undefined

    const coverageSeries: Series[] = ts
        ? [
              {
                  key: 'coverage',
                  label: 'Coverage',
                  data: ts.reads.total.map((total, i) => (total > 0 ? ts.reads.precomputed[i] / total : 0)),
              },
          ]
        : []

    const fallbackSeries: Series[] = ts ? [{ key: 'fallback', label: 'Fallback reads', data: ts.reads.fallback }] : []

    // One stacked series per exit code, biggest offenders first so the legend leads with them.
    const failureSeries: Series[] = ts
        ? Object.entries(ts.builds.failed_by_code)
              .sort((a, b) => b[1].reduce((s, v) => s + v, 0) - a[1].reduce((s, v) => s + v, 0))
              .map(([code, data]) => ({
                  key: code,
                  label: EXCEPTION_CODE_LABELS[code] ? `${code} (${EXCEPTION_CODE_LABELS[code]})` : code,
                  data,
              }))
        : []

    const wastedSeries: Series[] = ts
        ? [{ key: 'wasted', label: 'Wasted on failed builds', data: ts.builds.failed_read_bytes }]
        : []

    return (
        <div className="mb-6">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <h3 className="mb-0">Trends</h3>
                <div className="flex items-center gap-2">
                    {TIMESERIES_RANGE_OPTIONS.map(({ label, hours }) => (
                        <LemonButton
                            key={hours}
                            type={timeseriesHoursBack === hours ? 'primary' : 'tertiary'}
                            size="small"
                            onClick={() => setTimeseriesHoursBack(hours)}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
            </div>
            {!ts && precomputeTimeseriesLoading ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {[0, 1, 2, 3].map((i) => (
                        <LemonSkeleton key={i} className="h-56 w-full" />
                    ))}
                </div>
            ) : ts ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <ChartCard title="Precompute coverage (share of metric reads served precomputed)">
                        <TimeSeriesLineChart
                            series={coverageSeries}
                            labels={ts.buckets}
                            theme={theme}
                            config={{ xAxis, yAxis: { format: 'percentage' }, showGrid: true }}
                        />
                    </ChartCard>
                    <ChartCard title="Fallback reads (attempted precompute, fell back to direct scan)">
                        <TimeSeriesBarChart
                            series={fallbackSeries}
                            labels={ts.buckets}
                            theme={theme}
                            config={{ xAxis, showGrid: true }}
                        />
                    </ChartCard>
                    <ChartCard title="Failed builds by exit code">
                        <TimeSeriesBarChart
                            series={failureSeries}
                            labels={ts.buckets}
                            theme={theme}
                            config={{ xAxis, barLayout: 'stacked', showGrid: true, legend: { show: true } }}
                        />
                    </ChartCard>
                    <ChartCard title="Bytes wasted on failed builds">
                        <TimeSeriesBarChart
                            series={wastedSeries}
                            labels={ts.buckets}
                            theme={theme}
                            config={{
                                xAxis,
                                yAxis: { tickFormatter: (value: number) => humanizeBytes(value) },
                                tooltip: { valueFormatter: (value: number) => humanizeBytes(value) },
                                showGrid: true,
                            }}
                        />
                    </ChartCard>
                </div>
            ) : null}
        </div>
    )
}
