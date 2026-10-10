import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'
import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

function formatDays(days: number): string {
    const rounded = Number.isInteger(days) ? String(days) : days.toFixed(1)
    return rounded === '1' ? '1 day' : `${rounded} days`
}

function EstimatedCoverageBanner(): JSX.Element | null {
    const { scoringCoverage } = useValues(autoresearchPipelineLogic)
    if (!scoringCoverage) {
        return null
    }
    const { scored, eligible, rescoreDays } = scoringCoverage
    return (
        <LemonBanner type="info">
            The latest run scored {humanFriendlyNumber(scored)} of {humanFriendlyNumber(eligible)} users, starting with
            users never scored, then those scored longest ago. Everyone is rescored about every {rescoreDays} days.
        </LemonBanner>
    )
}

/** Measured coverage, never-scored count and rescore cadence. Falls back to the estimate for runs from before the measure. */
export function CoverageSummaryBanner(): JSX.Element | null {
    const { coverageSummary } = useValues(autoresearchPipelineLogic)
    if (!coverageSummary) {
        return <EstimatedCoverageBanner />
    }
    const { coverage, coveragePct, measuredAt, measuredRescoreDays, targetRescoreDays, failedRunsSince } =
        coverageSummary
    const slowerThanTarget = measuredRescoreDays != null && measuredRescoreDays > targetRescoreDays
    return (
        <LemonBanner type={failedRunsSince > 0 || slowerThanTarget ? 'warning' : 'info'}>
            <div className="space-y-1" data-attr="autoresearch-coverage-summary">
                <p className="mb-0">
                    {humanFriendlyNumber(coverage.with_score)} of {humanFriendlyNumber(coverage.population)} people (
                    {Math.round(coveragePct)}%) have a score from the last {formatDays(coverage.lookback_days)}.{' '}
                    {coverage.never_scored > 0
                        ? `${humanFriendlyNumber(coverage.never_scored)} people have no score in that time.`
                        : 'Everyone has a score.'}
                </p>
                {coverage.age_days_p50 != null && coverage.age_days_p90 != null && (
                    <p className="mb-0">
                        Half of the scores are less than {formatDays(coverage.age_days_p50)} old. 90% are less than{' '}
                        {formatDays(coverage.age_days_p90)} old.
                    </p>
                )}
                {measuredRescoreDays != null && (
                    <p className="mb-0">
                        Each person is rescored about every {formatDays(measuredRescoreDays)}
                        {measuredRescoreDays !== targetRescoreDays
                            ? `. The target is every ${formatDays(targetRescoreDays)}.`
                            : ', as planned.'}
                    </p>
                )}
                {failedRunsSince > 0 && (
                    <p className="mb-0">
                        {failedRunsSince === 1 ? '1 scoring run' : `${failedRunsSince} scoring runs`} failed after this
                        measure on {dayjs(measuredAt).format('MMM D')}, so these numbers can be out of date.
                    </p>
                )}
            </div>
        </LemonBanner>
    )
}

/** Coverage and score age per scoring day, from the runs list. */
export function CoverageHistoryChart(): JSX.Element {
    const { coverageHistory } = useValues(autoresearchPipelineLogic)
    const theme = useChartTheme()

    const series = useMemo<Series[]>(
        () => [
            {
                key: 'coverage',
                label: 'People with a score (%)',
                color: theme.colors[0],
                data: coverageHistory.map((p) => p.coveragePct),
            },
            {
                key: 'age_p50',
                label: 'Median score age (days)',
                color: theme.colors[1],
                data: coverageHistory.map((p) => p.ageP50Days ?? NaN),
                yAxisId: 'age',
            },
            {
                key: 'age_p90',
                label: '90th percentile score age (days)',
                color: theme.colors[2],
                data: coverageHistory.map((p) => p.ageP90Days ?? NaN),
                yAxisId: 'age',
            },
        ],
        [coverageHistory, theme]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            showCrosshair: true,
            xAxis: { interval: 'day', timezone: 'UTC' },
            yAxis: [
                { id: 'left', label: 'People with a score', format: 'percentage', min: 0, max: 100, showGrid: true },
                { id: 'age', position: 'right', label: 'Score age (days)', decimalPlaces: 1 },
            ],
            legend: { show: true },
        }),
        []
    )

    if (coverageHistory.length < 2) {
        return (
            <p className="text-sm text-muted mb-0">
                The chart needs two days of scoring runs that measured coverage. Check back after the next scoring run.
            </p>
        )
    }
    return (
        <div className="h-64 max-w-4xl">
            <TimeSeriesLineChart
                series={series}
                labels={coverageHistory.map((p) => p.day)}
                theme={theme}
                config={config}
                dataAttr="autoresearch-coverage-chart"
            />
        </div>
    )
}
