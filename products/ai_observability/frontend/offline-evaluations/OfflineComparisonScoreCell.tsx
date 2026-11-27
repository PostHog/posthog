import { Link, Tooltip } from '@posthog/lemon-ui'

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
        return <span className="text-muted">Scores unavailable</span>
    }
    if (row.kind === 'experiment') {
        const score = row.scores.get(experiment.id)
        return score ? (
            <OfflineExperimentScoreValue score={score} />
        ) : (
            <span className="text-muted">No score with this formula</span>
        )
    }
    const summary = row.scores.get(experiment.id)
    if (!summary) {
        return <span className="text-muted">No results for this version</span>
    }
    const counts = summary.status_counts
    const difference = experiment.id === baselineId ? null : aggregateDifference(summary, row.scores.get(baselineId))
    return (
        <div className="space-y-1">
            <OfflineSummaryMetrics summary={summary} />
            {difference && <div className="text-xs tabular-nums">{difference}</div>}
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
                    data-attr="offline-comparison-inspect-items"
                    className="text-xs tabular-nums"
                >
                    {counts.ok.toLocaleString()} of {summary.observed_item_count.toLocaleString()} items scored
                </Link>
            </Tooltip>
        </div>
    )
}
