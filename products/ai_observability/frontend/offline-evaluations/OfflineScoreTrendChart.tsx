import { useMemo } from 'react'

import { ScatterChart, TooltipSurface } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { OfflineHistoryPointApi } from '../generated/api.schemas'
import { buildOfflineTrendPanels, formatOfflineNumericScore, type OfflineTrendPeriod } from './offlineScoreTrends'

export interface OfflineScoreTrendChartProps {
    periods: OfflineTrendPeriod[]
    onPointClick?: (point: OfflineHistoryPointApi) => void
    timezone?: string
    heightClassName?: string
}

export function OfflineScoreTrendChart({
    periods,
    onPointClick,
    timezone = 'UTC',
    heightClassName = 'h-64',
}: OfflineScoreTrendChartProps): JSX.Element {
    const theme = useChartTheme()
    const panels = useMemo(() => buildOfflineTrendPanels(periods), [periods])

    if (panels.length === 0) {
        return <div className="text-muted p-8 text-center">No results in this period. Try a different date range.</div>
    }

    return (
        <div className="space-y-4 min-w-0">
            {panels.map((panel) => (
                <div key={panel.key} className="min-w-0">
                    <div className="text-xs text-muted mb-2">{panel.label}</div>
                    {panel.series.some((series) => series.points.length > 0) ? (
                        <div className={cn(heightClassName, 'min-w-0 flex flex-col')}>
                            <ScatterChart
                                series={panel.series}
                                theme={theme}
                                config={{
                                    xAxis: {
                                        domain: panel.xDomain,
                                        label: panel.elapsed
                                            ? 'Time from period start'
                                            : `Execution time (${timezone})`,
                                        tickFormatter: (value) =>
                                            panel.elapsed
                                                ? `${(value / 86400000).toLocaleString(undefined, { maximumFractionDigits: 1 })}d`
                                                : dayjs(value).tz(timezone).format('MMM D'),
                                    },
                                    yAxis: {
                                        domain: panel.yDomain,
                                        tickFormatter: (value) =>
                                            panel.percentage
                                                ? `${(value * 100).toFixed(0)}%`
                                                : formatOfflineNumericScore(value),
                                    },
                                    legend: { show: true },
                                }}
                                dataAttr="offline-score-trend"
                                onPointClick={(point) => point.meta && onPointClick?.(point.meta.point)}
                                tooltip={({ point }) => {
                                    const meta = point.meta
                                    if (!meta) {
                                        return null
                                    }
                                    const { experiment, summary } = meta.point
                                    return (
                                        <TooltipSurface>
                                            <div className="font-semibold">{experiment.name}</div>
                                            <div>{`${meta.period} · v${summary.scorer.version} · ${experiment.status}`}</div>
                                            <div>
                                                {dayjs(experiment.started_at)
                                                    .tz(timezone)
                                                    .format('MMM D, YYYY HH:mm:ss')}
                                            </div>
                                            <div>{`${meta.metric}: ${meta.percentage ? `${formatOfflineNumericScore(point.y * 100)}%` : formatOfflineNumericScore(point.y)}`}</div>
                                            <div>{`${summary.status_counts.ok} successful · ${summary.result_count - summary.status_counts.ok} other outcomes · ${summary.missing_result_count} missing`}</div>
                                            <div>{`${summary.distinct_case_count} distinct cases · ${summary.trial_item_count} trial items`}</div>
                                            <div>{`${experiment.run_source || 'Source not specified'}${experiment.suite_key ? ` · ${experiment.suite_key}` : ''}`}</div>
                                            {[
                                                experiment.application_version,
                                                experiment.model_version,
                                                experiment.prompt_version,
                                                experiment.dataset_revision_identifier,
                                            ]
                                                .filter(Boolean)
                                                .map((value, index) => (
                                                    <div key={index}>{value}</div>
                                                ))}
                                        </TooltipSurface>
                                    )
                                }}
                            />
                        </div>
                    ) : (
                        <div className="text-muted p-8 text-center">
                            These runs have no successful scores to plot. Their outcomes remain in the runs table.
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
}
