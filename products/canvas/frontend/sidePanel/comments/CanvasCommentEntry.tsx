import {
    Avatar,
    AvatarFallback,
    ThreadItem,
    ThreadItemAuthor,
    ThreadItemBody,
    ThreadItemContent,
    ThreadItemGutter,
    ThreadItemHeader,
    ThreadItemTimestamp,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { CommentType } from '~/types'

function authorName(comment: CommentType): string {
    return comment.created_by ? fullNameOrEmail(comment.created_by) : 'Someone'
}

/** One comment in a thread: who wrote it, when, and what it says. */
export function CanvasCommentEntry({ comment }: { comment: CommentType }): JSX.Element {
    const name = authorName(comment)
    return (
        <ThreadItem>
            <ThreadItemGutter>
                <Avatar size="sm">
                    <AvatarFallback>{name.slice(0, 1).toUpperCase()}</AvatarFallback>
                </Avatar>
            </ThreadItemGutter>
            <ThreadItemContent>
                <ThreadItemHeader>
                    <ThreadItemAuthor className="truncate">{name}</ThreadItemAuthor>
                    <ThreadItemTimestamp dateTime={comment.created_at} title={dayjs(comment.created_at).format('LLL')}>
                        {dayjs(comment.created_at).fromNow()}
                    </ThreadItemTimestamp>
                </ThreadItemHeader>
                <ThreadItemBody className="break-words whitespace-pre-wrap">{comment.content}</ThreadItemBody>
            </ThreadItemContent>
        </ThreadItem>
    )
}
