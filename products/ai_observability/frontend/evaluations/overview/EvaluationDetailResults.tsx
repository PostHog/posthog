import { useActions, useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { EvaluationBreakdownPicker } from './EvaluationBreakdownPicker'
import { evaluationDetailResultsLogic } from './evaluationDetailResultsLogic'
import { RATE_LIMITED_MESSAGE, hasIsolatedPoints } from './evaluationOverviewDisplay'
import { EvaluationResultCards } from './EvaluationResultCards'

export function EvaluationDetailResults({ evaluationId }: { evaluationId: string }): JSX.Element | null {
    const logic = evaluationDetailResultsLogic({ evaluationId })
    const {
        results,
        resultsLoading,
        details,
        detailsLoading,
        request,
        failure,
        breakdownProperty,
        breakdownSeries,
        breakdownSeriesLoading,
        breakdownFailure,
        trendsQuery,
    } = useValues(logic)
    const { loadResults, loadDetails, loadBreakdown, selectBucket, runOnPastData } = useActions(logic)
    const { timezone } = useValues(teamLogic)

    if (request.notice) {
        return <LemonBanner type="info">{request.notice}</LemonBanner>
    }
    if (failure) {
        return (
            <LemonBanner
                type={failure === 'rate_limited' ? 'warning' : 'error'}
                action={{
                    children: 'Try again',
                    onClick: () => loadResults(),
                    'data-attr': 'llma-evaluation-results-retry',
                }}
            >
                {failure === 'rate_limited' ? RATE_LIMITED_MESSAGE : "Couldn't load the results over time."}
            </LemonBanner>
        )
    }
    if (!results) {
        return resultsLoading ? <LemonSkeleton className="h-56 w-full" /> : null
    }
    const { row, buckets, interval } = results
    // Nothing graded leaves the runs table below to say so, so the cards would only repeat it.
    if (!row || row.gradedCount === 0) {
        return null
    }

    return (
        <EvaluationResultCards
            row={row}
            buckets={buckets}
            interval={interval}
            timezone={timezone}
            // A retry shows the skeleton, so the error's Try again can't be clicked again while it runs.
            details={detailsLoading ? null : details}
            onRetryDetails={() => loadDetails()}
            onSelectBucket={selectBucket}
            showFailingExamples={false}
            chartAction={trendsQuery ? <EvaluationBreakdownPicker evaluationId={evaluationId} /> : null}
            breakdown={breakdownProperty ? breakdownSeries : null}
            chartFooter={
                breakdownFailure ? (
                    <div className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
                        <span>
                            {breakdownFailure === 'rate_limited'
                                ? RATE_LIMITED_MESSAGE
                                : "Couldn't split the results by this property."}
                        </span>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => loadBreakdown()}
                            loading={breakdownSeriesLoading}
                            data-attr="llma-evaluation-results-breakdown-retry"
                        >
                            Try again
                        </LemonButton>
                    </div>
                ) : (
                    hasIsolatedPoints(row) && (
                        <div className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
                            <span>{`This evaluation has ${interval}s with no results, so some points have no line.`}</span>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconClockRewind />}
                                onClick={runOnPastData}
                                data-attr="llma-evaluation-results-backfill-hint"
                            >
                                Run on past data
                            </LemonButton>
                        </div>
                    )
                )
            }
        />
    )
}
