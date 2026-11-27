import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { aggregateDifference, type ComparisonRun, type ComparisonScoreRow } from './offlineComparison'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import { OfflineExperimentScoreValue } from './OfflineExperimentScoreValue'
import { OfflineSummaryMetrics } from './OfflineScoreSummaryDisplay'

export function OfflineComparisonScoreCell({
    row,
    run,
    baselineId,
}: {
    row: ComparisonScoreRow
    run: ComparisonRun
    baselineId: string
}): JSX.Element {
    const { experiment } = run
    if (experiment.visible_scorer_version_count === null) {
        return <span className="text-xs text-muted">Scores unavailable</span>
    }
    if (row.kind === 'experiment') {
        const score = row.scores.get(experiment.id)
        return score ? (
            <OfflineExperimentScoreValue score={score} />
        ) : (
            <span className="text-xs text-muted">No score with this formula</span>
        )
    }
    const summary = row.scores.get(experiment.id)
    if (!summary) {
        return <span className="text-xs text-muted">No results for this version</span>
    }
    const counts = summary.status_counts
    const difference = experiment.id === baselineId ? null : aggregateDifference(summary, row.scores.get(baselineId))
    return (
        <div className="flex flex-col items-start gap-0.5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <div className="text-sm">
                    <OfflineSummaryMetrics summary={summary} showMetricLabel={false} />
                </div>
                {difference && (
                    <span
                        className={cn(
                            'text-xs tabular-nums whitespace-nowrap',
                            difference.outcome === 'better' && 'font-semibold text-success',
                            difference.outcome === 'worse' && 'font-semibold text-danger',
                            difference.outcome === 'neutral' && 'text-muted'
                        )}
                    >
                        {difference.label}
                        {difference.outcome !== 'neutral' && ` ${difference.outcome}`}
                    </span>
                )}
            </div>
            <Tooltip
                title={[
                    `${counts.ok} successful`,
                    `${counts.error} errors`,
                    `${counts.skipped} skipped`,
                    `${counts.not_applicable} not applicable`,
                    `${summary.missing_result_count} missing`,
                    `${summary.not_requested_count} not requested`,
                ].join(' · ')}
            >
                <Link
                    to={offlineExperimentUrl({ experiment, summary })}
                    target="_blank"
                    targetBlankIcon
                    data-attr="offline-comparison-inspect-items"
                    className="text-[11px] leading-4 tabular-nums hover:underline [&_svg]:text-muted"
                >
                    <span className="text-muted">
                        {counts.ok.toLocaleString()} of {summary.observed_item_count.toLocaleString()} scored
                    </span>
                </Link>
            </Tooltip>
        </div>
    )
}
