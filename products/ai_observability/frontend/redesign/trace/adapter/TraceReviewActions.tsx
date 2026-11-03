import { LemonButton } from '@posthog/lemon-ui'

import type { TraceReviewStatusApi } from '../../../generated/api.schemas'
import { ReviewQueuePickerModal } from '../../../reviewQueues/ReviewQueuePickerModal'
import { TraceReviewButton } from '../../../traceReviews/TraceReviewButton'

export interface TraceReviewActionsProps {
    traceId: string
    status: TraceReviewStatusApi | null
    loading: boolean
    failed: boolean
    onQueueChanged: () => void
}

export function TraceReviewActions({
    traceId,
    status,
    loading,
    failed,
    onQueueChanged,
}: TraceReviewActionsProps): JSX.Element | null {
    if (!status) {
        return loading || !failed ? null : (
            <LemonButton
                type="secondary"
                size="small"
                disabledReason="Couldn't load this trace's review. Reload the page to try again."
            >
                Review
            </LemonButton>
        )
    }
    const { review, queue } = status
    return (
        <>
            <TraceReviewButton
                traceId={traceId}
                queueId={queue?.id ?? null}
                buttonType="secondary"
                buttonSize="small"
                buttonLabel={review ? 'Edit review' : 'Review'}
            />
            {review ? null : (
                <ReviewQueuePickerModal
                    traceId={traceId}
                    queueItemId={queue?.itemId ?? null}
                    defaultQueueId={queue?.id ?? null}
                    confirmLabel={queue ? 'Change queue' : 'Add to queue'}
                    buttonType="secondary"
                    buttonSize="small"
                    onSuccess={onQueueChanged}
                />
            )}
        </>
    )
}
