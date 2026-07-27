import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { TraceReview } from './types'
import {
    getHiddenTraceReviewScoreCount,
    getTraceReviewScores,
    getTraceReviewScoreDisplayValue,
    getTraceReviewScoreTagLabel,
    getTraceReviewerName,
    getVisibleTraceReviewScores,
} from './utils'

export function TraceReviewTooltipContent({ review }: { review: TraceReview }): JSX.Element {
    const reviewerName = getTraceReviewerName(review)
    const scores = getTraceReviewScores(review)

    return (
        <div className="max-w-96 space-y-2">
            {reviewerName ? (
                <div>
                    <span className="font-semibold">Reviewed by:</span> {reviewerName}
                </div>
            ) : null}
            {review.updated_at ? (
                <div>
                    <span className="font-semibold">Reviewed at:</span> <TZLabel time={review.updated_at} />
                </div>
            ) : null}
            {scores.length > 0 ? (
                <div className="space-y-1">
                    <div className="font-semibold">Scores</div>
                    <div className="space-y-1">
                        {scores.map((score) => (
                            <div key={score.id}>
                                <span className="font-medium">{score.definition_name}:</span>{' '}
                                {getTraceReviewScoreDisplayValue(score)}
                            </div>
                        ))}
                    </div>
                </div>
            ) : null}
            {review.comment ? (
                <div className="space-y-1">
                    <div className="font-semibold">Reasoning</div>
                    <div className="whitespace-pre-wrap break-words">{review.comment}</div>
                </div>
            ) : null}
        </div>
    )
}

export function TraceReviewTooltip({ review, children }: { review: TraceReview; children: JSX.Element }): JSX.Element {
    const reviewerName = getTraceReviewerName(review)
    const hasTooltip =
        getTraceReviewScores(review).length > 0 || !!review.comment || !!review.updated_at || !!reviewerName

    if (!hasTooltip) {
        return children
    }

    return <Tooltip title={<TraceReviewTooltipContent review={review} />}>{children}</Tooltip>
}

export interface TraceReviewTagItem {
    key: string
    label: string
    type: React.ComponentProps<typeof LemonTag>['type']
}

export function getTraceReviewTagItems({
    review,
    maxVisibleScores,
    tagTypeOverride,
}: {
    review: TraceReview
    maxVisibleScores: number
    tagTypeOverride?: React.ComponentProps<typeof LemonTag>['type']
}): TraceReviewTagItem[] {
    const scores = getTraceReviewScores(review)

    if (scores.length === 0) {
        return [{ key: 'reviewed', label: 'Reviewed', type: tagTypeOverride ?? 'success' }]
    }

    const visibleScores = getVisibleTraceReviewScores(review, maxVisibleScores)
    const hiddenScoreCount = getHiddenTraceReviewScoreCount(review, maxVisibleScores)

    return [
        ...visibleScores.map((score) => ({
            key: score.id,
            label: getTraceReviewScoreTagLabel(score),
            type: tagTypeOverride ?? 'completion',
        })),
        ...(hiddenScoreCount > 0
            ? [{ key: 'overflow', label: `+${hiddenScoreCount} more`, type: tagTypeOverride ?? 'completion' }]
            : []),
    ]
}

function renderTraceReviewTags({
    items,
    size,
    className,
    onClick,
}: {
    items: TraceReviewTagItem[]
    size: 'small' | 'medium'
    className?: string
    onClick?: () => void
}): JSX.Element {
    const tagNodes = items.map((item) => (
        <LemonTag key={item.key} size={size} type={item.type} className={className} onClick={onClick}>
            <span className="inline-block max-w-64 truncate align-bottom">{item.label}</span>
        </LemonTag>
    ))

    if (tagNodes.length === 1) {
        return tagNodes[0]
    }

    return <div className="flex flex-wrap items-center gap-1">{tagNodes}</div>
}

export function TraceReviewValue({
    review,
    size = 'small',
    className,
    onClick,
    maxVisibleScores = 2,
    tagTypeOverride,
}: {
    review: TraceReview
    size?: 'small' | 'medium'
    className?: string
    onClick?: () => void
    maxVisibleScores?: number
    tagTypeOverride?: React.ComponentProps<typeof LemonTag>['type']
}): JSX.Element {
    return (
        <TraceReviewTooltip review={review}>
            {renderTraceReviewTags({
                items: getTraceReviewTagItems({ review, maxVisibleScores, tagTypeOverride }),
                size,
                className,
                onClick,
            })}
        </TraceReviewTooltip>
    )
}

export function TraceReviewStatusTag({
    review,
    size = 'small',
    className,
    onClick,
    maxVisibleScores = 3,
    tagTypeOverride,
}: {
    review: TraceReview | null
    size?: 'small' | 'medium'
    className?: string
    onClick?: () => void
    maxVisibleScores?: number
    tagTypeOverride?: React.ComponentProps<typeof LemonTag>['type']
}): JSX.Element {
    if (!review) {
        return (
            <LemonTag size={size} type={tagTypeOverride ?? 'muted'} className={className} onClick={onClick}>
                Not reviewed
            </LemonTag>
        )
    }

    return (
        <TraceReviewTooltip review={review}>
            {renderTraceReviewTags({
                items: getTraceReviewTagItems({ review, maxVisibleScores, tagTypeOverride }),
                size,
                className,
                onClick,
            })}
        </TraceReviewTooltip>
    )
}
