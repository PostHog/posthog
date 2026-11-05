import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceHumanReviewApi, TraceReviewStatusApi } from '../../../generated/api.schemas'

export interface ReviewChipProps {
    status: TraceReviewStatusApi
    queueHref: string | null
    onRemoveFromQueue?: (() => void) | null
}

function ReviewTooltip({ review }: { review: TraceHumanReviewApi }): JSX.Element {
    return (
        <div className="flex max-w-80 flex-col gap-1">
            <span className="font-semibold">{review.reviewedBy ? `Reviewed by ${review.reviewedBy}` : 'Reviewed'}</span>
            <TZLabel time={review.reviewedAt} className="opacity-75" />
            {review.scores.map((score, index) => (
                <span key={`${score.name}-${index}`}>{score.label}</span>
            ))}
            {review.comment ? (
                <span className="line-clamp-4 whitespace-pre-wrap opacity-75">{review.comment}</span>
            ) : null}
        </div>
    )
}

export function ReviewChip({ status, queueHref, onRemoveFromQueue = null }: ReviewChipProps): JSX.Element | null {
    const { review, queue } = status
    if (!review && !queue) {
        return null
    }
    const scoreCount = review?.scores.length ?? 0
    return (
        <>
            {review ? (
                <Tooltip title={<ReviewTooltip review={review} />}>
                    <LemonTag weight="normal" type="success" icon={<IconCheck />} data-attr="trace-view-review-chip">
                        {scoreCount > 0
                            ? `Reviewed · ${scoreCount} ${scoreCount === 1 ? 'score' : 'scores'}`
                            : 'Reviewed'}
                    </LemonTag>
                </Tooltip>
            ) : null}
            {queue ? (
                <LemonTag weight="normal" className="max-w-full" data-attr="trace-view-review-queue-chip">
                    <Tooltip title="Open the review queue">
                        <Link to={queueHref ?? undefined} subtle className="min-w-0">
                            <span className="shrink-0">Queue:&nbsp;</span>
                            <span className="max-w-60 truncate">{queue.name}</span>
                        </Link>
                    </Tooltip>
                    {onRemoveFromQueue ? (
                        <LemonButton
                            size="xxsmall"
                            noPadding
                            icon={<IconX />}
                            onClick={onRemoveFromQueue}
                            tooltip="Remove from queue"
                            aria-label="Remove from queue"
                            className="-my-0.5 ml-1"
                            data-attr="trace-view-remove-from-queue"
                        />
                    ) : null}
                </LemonTag>
            ) : null}
        </>
    )
}
