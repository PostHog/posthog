import { CommentWithRepliesType } from 'lib/components/Comments/commentsLogic'
import { dayjs } from 'lib/dayjs'

import { CommentType } from '~/types'

const CONTINUATION_WINDOW_MINUTES = 5

/**
 * Whether a comment reads as a continuation of the one before it, so it drops its avatar and header.
 * Tasks and Slack-synced comments keep their header, because their badge is part of what they say.
 */
function isContinuationOf(previous: CommentType | undefined, comment: CommentType): boolean {
    if (!previous || !previous.created_by || !comment.created_by) {
        return false
    }
    if (comment.is_task || comment.item_context?.from_slack || previous.item_context?.from_slack) {
        return false
    }
    if (previous.created_by.id !== comment.created_by.id) {
        return false
    }
    const gap = dayjs(comment.created_at).diff(dayjs(previous.created_at), 'minute', true)
    return gap >= 0 && gap < CONTINUATION_WINDOW_MINUTES
}

/**
 * The comments that render as continuation rows, in thread roots and replies alike.
 * A root continues the root before it only when that thread has no replies and this one is collapsed,
 * because an open thread's root heads its replies and needs its author shown.
 */
export function getContinuationIds(
    threads: CommentWithRepliesType[],
    expandedThreadIds: Set<CommentWithRepliesType['id']>
): Set<CommentType['id']> {
    const ids = new Set<CommentType['id']>()
    threads.forEach((thread, index) => {
        const previous = threads[index - 1]
        if (
            thread.comment &&
            !expandedThreadIds.has(thread.id) &&
            !previous?.replies.length &&
            isContinuationOf(previous?.comment, thread.comment)
        ) {
            ids.add(thread.comment.id)
        }
        thread.replies.forEach((reply, replyIndex) => {
            if (isContinuationOf(thread.replies[replyIndex - 1], reply)) {
                ids.add(reply.id)
            }
        })
    })
    return ids
}
