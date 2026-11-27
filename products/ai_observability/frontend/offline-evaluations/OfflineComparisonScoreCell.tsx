import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import {
    aggregateDifference,
    experimentScoreDifference,
    type ComparisonRun,
    type ComparisonScoreRow,
    type ScoreDifference,
} from './offlineComparison'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import { OfflineExperimentScoreValue } from './OfflineExperimentScoreValue'
import { OfflineSummaryMetrics } from './OfflineScoreSummaryDisplay'
import { formatOfflinePercentage } from './offlineScoreTrends'
import { offlineUnscoredLabel } from './offlineUnscoredLabel'

function BaselineDifference({ difference }: { difference: ScoreDifference | null }): JSX.Element | null {
    return (
        difference && (
            <span
                className={cn(
                    'text-xs tabular-nums whitespace-nowrap',
                    difference.outcome === 'better' && 'font-semibold text-success',
                    difference.outcome === 'worse' && 'font-semibold text-danger',
                    difference.outcome === 'neutral' && 'text-muted'
                )}
            >
                {difference.label}
            </span>
        )
    )
}

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
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <OfflineExperimentScoreValue score={score} comparisonScores={row.scores} />
                {experiment.id !== baselineId && (
                    <BaselineDifference difference={experimentScoreDifference(score, row.scores.get(baselineId))} />
                )}
            </div>
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
    const categoryPassRate = summary.scorer.kind === 'categorical' ? summary.pass_rate : null
    const metrics = (
        <div className="text-sm">
            <OfflineSummaryMetrics summary={summary} showMetricLabel={false} />
        </div>
    )
    return (
        <div className="flex flex-col items-start gap-0.5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                {categoryPassRate !== null ? (
                    <span className="text-sm">
                        <strong className="font-semibold tabular-nums">
                            {formatOfflinePercentage(categoryPassRate)}
                        </strong>{' '}
                        <span className="text-xs text-muted">Pass rate</span>
                    </span>
                ) : (
                    metrics
                )}
                <BaselineDifference difference={difference} />
            </div>
            {categoryPassRate !== null && metrics}
            <Tooltip
                title={[
                    `${counts.ok} successful`,
                    `${counts.error} errors`,
                    `${counts.skipped} skipped`,
                    `${counts.not_applicable} not applicable`,
                    offlineUnscoredLabel(summary),
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
