import { useMemo } from 'react'

import { TimeSeriesComboChart, TooltipSurface } from '@posthog/quill-charts'
import type { Series, TimeSeriesComboChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { withAlpha } from '../overview/evaluationOverviewDisplay'
import type { EvaluationReportRun } from '../types'
import { reportHeadline } from './reportHeadline'

const RESULTS_KEY = 'results'
const RESULTS_CEILING_KEY = 'results-ceiling'
/** Result bars use at most this share of the plot height, so they read as context behind the line. */
const RESULTS_HEIGHT_SHARE = 1 / 3

/** One point per loaded report, oldest first, from the totals each report stored. */
export function EvaluationReportsTrendChart({
    reportRuns,
    timezone,
}: {
    reportRuns: EvaluationReportRun[]
    timezone: string
}): JSX.Element | null {
    const theme = useChartTheme()
    const points = useMemo(
        () =>
            [...reportRuns]
                .reverse()
                .map((run) => ({ run, headline: reportHeadline(run) }))
                .filter(({ headline }) => headline !== null),
        [reportRuns]
    )
    const label = points[0]?.headline?.label ?? 'Pass rate'

    const series = useMemo<Series[]>(() => {
        const totals = points.map(({ headline }) => headline?.total ?? NaN)
        const ceiling = Math.max(1, ...totals.filter(Number.isFinite)) / RESULTS_HEIGHT_SHARE
        return [
            {
                key: RESULTS_KEY,
                label: 'Results',
                data: totals,
                type: 'bar',
                yAxisId: RESULTS_KEY,
                color: withAlpha(getColorVar('muted'), 0.3),
            },
            // The combo chart ignores axis bounds, so an invisible line at the ceiling keeps the bars low.
            {
                key: RESULTS_CEILING_KEY,
                label: '',
                data: totals.map(() => ceiling),
                type: 'line',
                yAxisId: RESULTS_KEY,
                color: 'transparent',
                visibility: { tooltip: false, total: false, valueLabel: false },
            },
            {
                key: 'headline',
                label,
                data: points.map(({ headline }) => headline?.value ?? NaN),
                type: 'line',
                color: theme.colors[0],
                points: { radius: 3 },
            },
        ]
    }, [points, label, theme])
    const config = useMemo<TimeSeriesComboChartConfig>(
        () => ({
            xAxis: { timezone, interval: 'day' },
            curve: 'linear',
            yAxis: [
                { id: 'left', showGrid: true, format: 'percentage' },
                { id: RESULTS_KEY, position: 'right', hide: true },
            ],
            valueDomain: { min: 0, max: 100 },
            margins: { right: 16 },
        }),
        [timezone]
    )

    // One report says nothing about a trend.
    if (points.length < 2) {
        return null
    }

    const tooltip = (ctx: TooltipContext): JSX.Element => {
        const point = points[ctx.dataIndex]
        return (
            <TooltipSurface>
                <div className="font-semibold max-w-60 truncate">{point?.run.content?.title || 'Report'}</div>
                <div className="flex items-center gap-2 mt-1">
                    <span>{label}</span>
                    <strong className="ml-auto tabular-nums">{`${point?.headline?.value.toFixed(1)}%`}</strong>
                </div>
                <div className="flex items-center gap-2 opacity-70">
                    <span>Results</span>
                    <span className="ml-auto tabular-nums">{humanFriendlyNumber(point?.headline?.total ?? 0)}</span>
                </div>
            </TooltipSurface>
        )
    }

    return (
        <section className="flex flex-col gap-2 rounded border bg-surface-primary p-3">
            <h4 className="mb-0 text-sm font-semibold">{`${label} in each report`}</h4>
            <div className="h-40 min-w-0 flex flex-col">
                <TimeSeriesComboChart
                    series={series}
                    labels={points.map(({ run }) => run.period_end)}
                    theme={theme}
                    config={config}
                    tooltip={tooltip}
                />
            </div>
        </section>
    )
}
