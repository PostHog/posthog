import { IconCheck } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { TraceReviewStatusApi } from '../../../generated/api.schemas'
import { ChipTag } from '../../trace/components/ChipTag'

export interface TraceReviewCellProps {
    review: TraceReviewStatusApi | null
}

export function TraceReviewCell({ review }: TraceReviewCellProps): JSX.Element | null {
    if (!review?.review && !review?.queue) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-1">
            {review.review ? (
                <ChipTag type="success" size="small" icon={<IconCheck />}>
                    Reviewed
                </ChipTag>
            ) : null}
            {review.queue ? (
                <LemonTag size="small" title={review.queue.name}>
                    In queue
                </LemonTag>
            ) : null}
        </div>
    )
}
