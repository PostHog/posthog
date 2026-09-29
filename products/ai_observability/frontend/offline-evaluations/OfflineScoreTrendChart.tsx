import type { BuiltLogic } from 'kea'
import { useMemo } from 'react'

import { ScatterChart, TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { OfflineHistoryPointApi } from '../generated/api.schemas'
import type { offlineExperimentsLogicType } from './offlineExperimentsLogic'
import { OfflineScoreTrendCrosshair } from './OfflineScoreTrendCrosshair'
import { OfflineScoreTrendLines } from './OfflineScoreTrendLines'
import { buildOfflineTrendPanels, formatOfflineNumericScore, type OfflineTrendPeriod } from './offlineScoreTrends'

export interface OfflineScoreTrendChartProps {
    periods: OfflineTrendPeriod[]
    onPointClick?: (point: OfflineHistoryPointApi) => void
    timezone?: string
    heightClassName?: string
    colorOffset?: number
    hoverLogic?: BuiltLogic<offlineExperimentsLogicType>
}

export function OfflineScoreTrendChart({
    periods,
    onPointClick,
    timezone = 'UTC',
    heightClassName = 'h-64',
    colorOffset = 0,
    hoverLogic,
}: OfflineScoreTrendChartProps): JSX.Element {
    const baseTheme = useChartTheme()
    const theme = useMemo(
        () => ({
            ...baseTheme,
            colors: baseTheme.colors.map(
                (_, index) => baseTheme.colors[(index + colorOffset) % baseTheme.colors.length]
            ),
        }),
        [baseTheme, colorOffset]
    )
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
                                    showCrosshair: !hoverLogic,
                                    xAxis: {
                                        domain: panel.xDomain,
                                        label: panel.elapsed ? 'Time from period start' : undefined,
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
                                        <TooltipSurface data-attr="offline-score-trend-tooltip">
                                            <div className="font-semibold text-sm break-words">{experiment.name}</div>
                                            <div className="opacity-70 mt-0.5">
                                                {`${dayjs(experiment.started_at).tz(timezone).format('MMM D, YYYY HH:mm:ss')} (${timezone})`}
                                            </div>
                                            <div className="mt-2 pt-2 border-t border-current/25">
                                                <div className="flex items-center gap-2 font-medium">
                                                    <TooltipSwatch color={point.color} />
                                                    <span className="break-words">{`${summary.scorer.name} · v${summary.scorer.version}`}</span>
                                                </div>
                                                <div className="flex items-baseline justify-between gap-4 mt-1">
                                                    <span className="opacity-70">{meta.metric}</span>
                                                    <strong className="text-lg tabular-nums">
                                                        {meta.percentage
                                                            ? `${formatOfflineNumericScore(point.y * 100)}%`
                                                            : formatOfflineNumericScore(point.y)}
                                                    </strong>
                                                </div>
                                                {periods.length > 1 && <div className="opacity-70">{meta.period}</div>}
                                            </div>
                                            <div className="mt-2 pt-2 border-t border-current/25">
                                                <div className="font-medium mb-1">Result coverage</div>
                                                <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 mb-0">
                                                    <dt className="opacity-70">Successful</dt>
                                                    <dd className="text-right tabular-nums mb-0">
                                                        {summary.status_counts.ok}
                                                    </dd>
                                                    <dt className="opacity-70">Other outcomes</dt>
                                                    <dd className="text-right tabular-nums mb-0">
                                                        {summary.result_count - summary.status_counts.ok}
                                                    </dd>
                                                    <dt className="opacity-70">Missing</dt>
                                                    <dd className="text-right tabular-nums mb-0">
                                                        {summary.missing_result_count}
                                                    </dd>
                                                </dl>
                                                <div className="opacity-70 mt-1">{`${summary.distinct_case_count} distinct cases · ${summary.trial_item_count} trial items`}</div>
                                            </div>
                                            <div className="mt-2 pt-2 border-t border-current/25">
                                                <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 mb-0">
                                                    {[
                                                        ['Source', experiment.run_source || 'Not specified'],
                                                        ['Upload state', experiment.status],
                                                        ['Suite', experiment.suite_key],
                                                        ['Application', experiment.application_version],
                                                        ['Model', experiment.model_version],
                                                        ['Prompt', experiment.prompt_version],
                                                        ['Dataset revision', experiment.dataset_revision_identifier],
                                                    ]
                                                        .filter(([, value]) => value)
                                                        .map(([label, value]) => (
                                                            <div key={label} className="contents">
                                                                <dt className="opacity-70">{label}</dt>
                                                                <dd className="text-right break-words mb-0">{value}</dd>
                                                            </div>
                                                        ))}
                                                </dl>
                                            </div>
                                            {onPointClick && <TooltipFooter>Click to inspect experiment</TooltipFooter>}
                                        </TooltipSurface>
                                    )
                                }}
                            >
                                <OfflineScoreTrendLines />
                                {hoverLogic && panel.xDomain && (
                                    <OfflineScoreTrendCrosshair logic={hoverLogic} xDomain={panel.xDomain} />
                                )}
                            </ScatterChart>
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
