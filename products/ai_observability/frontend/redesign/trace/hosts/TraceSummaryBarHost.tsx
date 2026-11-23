import { useActions, useValues } from 'kea'

import { TraceSummaryBar } from '../components/TraceSummaryBar'
import { traceClustersLogic } from '../traceClustersLogic'
import { traceFeedbackLogic } from '../traceFeedbackLogic'
import { traceGitPullRequestLogic } from '../traceGitPullRequestLogic'
import { traceReviewLogic } from '../traceReviewLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'
import { confirmRemoveFromQueue } from './confirmRemoveFromQueue'

export function TraceSummaryBarHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element | null {
    const { trace, overview, seed, evaluationResults } = useValues(traceViewLogic({ traceId, timestampHint }))
    const { showFailingEvals, showFeedback } = useActions(traceViewModelLogic({ hostId, traceId, timestampHint }))
    const { clusters } = useValues(traceClustersLogic({ traceId }))
    const { traceFeedback } = useValues(traceFeedbackLogic({ traceId, timestampHint }))
    const { pullRequest } = useValues(traceGitPullRequestLogic({ traceId, timestampHint }))
    const reviewLogic = traceReviewLogic({ traceId })
    const { reviewStatus, queueHref, canEditReviews, removeFromQueueLoading } = useValues(reviewLogic)
    const { removeFromQueue } = useActions(reviewLogic)

    if (!overview) {
        return null
    }
    if (!trace) {
        return <TraceSummaryBar overview={overview} person={seed?.person ?? null} />
    }
    const queue = reviewStatus?.queue ?? null
    return (
        <TraceSummaryBar
            overview={overview}
            person={trace.person}
            clusters={clusters}
            evals={evaluationResults ? { summary: evaluationResults.summary, onClick: showFailingEvals } : null}
            feedback={
                traceFeedback ? { summary: traceFeedback.summary, onClick: () => showFeedback(null, 'chip') } : null
            }
            git={trace.git ? { ...trace.git, pullRequest } : null}
            review={
                reviewStatus
                    ? {
                          status: reviewStatus,
                          queueHref,
                          onRemoveFromQueue:
                              canEditReviews && queue && !removeFromQueueLoading
                                  ? () => confirmRemoveFromQueue(queue.name, removeFromQueue)
                                  : null,
                      }
                    : null
            }
        />
    )
}
