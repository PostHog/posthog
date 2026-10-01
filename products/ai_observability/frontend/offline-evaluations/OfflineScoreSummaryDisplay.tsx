import { IconCheck, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { offlineScorePasses } from './offlineScoreInterpretation'
import {
    formatOfflinePercentage,
    formatOfflineScore,
    offlineScoreMetricLabel,
    type OfflineScoreSummary,
} from './offlineScoreTrends'

export function OfflineScoreSummaryDisplay({ summary }: { summary: OfflineScoreSummary }): JSX.Element {
    const meanPassed = summary.scorer.kind === 'numeric' ? offlineScorePasses(summary.mean, summary.scorer) : null
    return (
        <div className="min-w-0 flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-1">
                {meanPassed === null ? (
                    <strong className="break-words tabular-nums" translate="no">
                        {formatOfflineScore(summary)}
                    </strong>
                ) : (
                    <LemonTag
                        type={meanPassed ? 'success' : 'danger'}
                        icon={meanPassed ? <IconCheck /> : <IconX />}
                        title={meanPassed ? 'Mean meets the passing rule' : 'Mean does not meet the passing rule'}
                    >
                        <span translate="no">{formatOfflineScore(summary)}</span>
                    </LemonTag>
                )}
                <span className="text-xs text-muted">{offlineScoreMetricLabel(summary.scorer)}</span>
            </div>
            {summary.pass_count != null && summary.fail_count != null && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs tabular-nums">
                    {summary.scorer.kind === 'numeric' && summary.pass_rate != null && (
                        <span>{`${formatOfflinePercentage(summary.pass_rate)} pass rate`}</span>
                    )}
                    <span className="text-success flex items-center gap-0.5">
                        <IconCheck />
                        <span>{`${summary.pass_count} passed`}</span>
                    </span>
                    <span className="text-danger flex items-center gap-0.5">
                        <IconX />
                        <span>{`${summary.fail_count} failed`}</span>
                    </span>
                </div>
            )}
        </div>
    )
}
