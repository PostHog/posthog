import type { TraceReviewStatusApi } from '../../../generated/api.schemas'
import { ReviewQueuePickerModal } from '../../../reviewQueues/ReviewQueuePickerModal'
import { TraceReviewButton } from '../../../traceReviews/TraceReviewButton'

export interface TraceReviewActionsProps {
    traceId: string
    status: TraceReviewStatusApi | null
    failed: boolean
    onQueueChanged: () => void
}

// No queue id goes to the review button: saving a review then clears whichever queue holds the trace, so a stale status
// can never point the save at the wrong queue.
export function TraceReviewActions({
    traceId,
    status,
    failed,
    onQueueChanged,
}: TraceReviewActionsProps): JSX.Element | null {
    if (!status && !failed) {
        return null
    }
    const queue = status?.queue ?? null
    return (
        <>
            <TraceReviewButton
                traceId={traceId}
                buttonType="secondary"
                buttonSize="small"
                buttonLabel={status ? (status.review ? 'Edit review' : 'Review') : undefined}
            />
            {status && !failed && !status.review ? (
                <ReviewQueuePickerModal
                    traceId={traceId}
                    queueItemId={queue?.itemId ?? null}
                    defaultQueueId={queue?.id ?? null}
                    confirmLabel={queue ? 'Change queue' : 'Add to queue'}
                    buttonType="secondary"
                    buttonSize="small"
                    onSuccess={onQueueChanged}
                />
            ) : null}
        </>
    )
}
