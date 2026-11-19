import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import {
    AvatarGroup,
    Text,
    ThreadItemGroup,
    ThreadItemReplies,
    ThreadItemRepliesLabel,
    ThreadItemRepliesMeta,
} from '@posthog/quill'

import { CommentsLogicProps, CommentWithRepliesType, commentsLogic } from 'lib/components/Comments/commentsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { CommentType } from '~/types'

import { QuillComment } from './QuillComment'
import { QuillCommentAvatar } from './QuillCommentAvatar'
import { QuillCommentComposer } from './QuillCommentComposer'

const MAX_REPLY_AVATARS = 3

interface QuillCommentThreadProps {
    thread: CommentWithRepliesType
    /** The reply composer mounts at the thread's end while this thread is the reply target. */
    logicProps: CommentsLogicProps
    continuationIds: Set<CommentType['id']>
}

export function QuillCommentThread({ thread, logicProps, continuationIds }: QuillCommentThreadProps): JSX.Element {
    const { replyingCommentId, expandedThreadIds } = useValues(commentsLogic)
    const { setReplyingComment, setThreadExpanded } = useActions(commentsLogic)
    const { comment, replies } = thread
    const composerRef = useRef<HTMLDivElement>(null)

    // The reply target always resolves to the thread root, and it is always expanded.
    const isReplyTarget = replyingCommentId === thread.id
    const isExpanded = expandedThreadIds.has(thread.id)
    const showReplies = isExpanded && replies.length > 0
    const latestReply = replies[replies.length - 1]
    const replyAuthors = replies.filter(
        (reply, index) =>
            replies.findIndex((other) => other.created_by?.id === reply.created_by?.id) === index && reply.created_by
    )

    const collapse = (): void => {
        if (isReplyTarget) {
            setReplyingComment(null)
        }
        setThreadExpanded(thread.id, false)
    }

    const replySummary =
        replies.length > 0 ? (
            <ThreadItemReplies
                className="mt-1.5"
                onClick={isExpanded ? collapse : () => setThreadExpanded(thread.id, true)}
                aria-expanded={isExpanded}
                data-attr={isExpanded ? 'comment-thread-collapse' : 'comment-thread-toggle'}
            >
                <AvatarGroup size="xs">
                    {replyAuthors.slice(0, MAX_REPLY_AVATARS).map((reply) => (
                        <QuillCommentAvatar key={reply.id} comment={reply} size="xs" />
                    ))}
                </AvatarGroup>
                <ThreadItemRepliesLabel>
                    {isExpanded ? 'Hide replies' : pluralize(replies.length, 'reply', 'replies')}
                </ThreadItemRepliesLabel>
                {!isExpanded && latestReply?.created_at && (
                    <ThreadItemRepliesMeta>
                        <TZLabel time={latestReply.created_at} />
                    </ThreadItemRepliesMeta>
                )}
            </ThreadItemReplies>
        ) : null

    // In a long thread the reply composer mounts below the fold.
    useEffect(() => {
        if (isReplyTarget) {
            composerRef.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [isReplyTarget])

    return (
        <section aria-label="Comment thread" className="flex flex-col" data-attr="discussions-thread">
            {comment ? (
                <QuillComment comment={comment} isContinuation={continuationIds.has(comment.id)}>
                    {replySummary}
                </QuillComment>
            ) : (
                <div className="flex flex-col gap-1 py-1.5 ps-14 pe-2">
                    <Text size="xs" variant="muted" render={<span className="m-0 italic" />}>
                        This comment was deleted
                    </Text>
                    {replySummary}
                </div>
            )}
            {(showReplies || isReplyTarget) && (
                <div className="ms-8 flex flex-col border-l border-border ps-2">
                    {showReplies && (
                        <ThreadItemGroup>
                            {replies.map((reply) => (
                                <QuillComment
                                    key={reply.id}
                                    comment={reply}
                                    isContinuation={continuationIds.has(reply.id)}
                                />
                            ))}
                        </ThreadItemGroup>
                    )}
                    {isReplyTarget && (
                        <div ref={composerRef} className="ps-14 pe-2 pt-1">
                            <QuillCommentComposer logicProps={logicProps} />
                        </div>
                    )}
                </div>
            )}
        </section>
    )
}
