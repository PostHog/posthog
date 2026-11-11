import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import {
    AvatarGroup,
    Button,
    Text,
    ThreadItemGroup,
    ThreadItemReplies,
    ThreadItemRepliesLabel,
    ThreadItemRepliesMeta,
    cn,
} from '@posthog/quill'

import { CommentsLogicProps, CommentWithRepliesType, commentsLogic } from 'lib/components/Comments/commentsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { QuillComment } from './QuillComment'
import { QuillCommentAvatar } from './QuillCommentAvatar'
import { QuillCommentComposer } from './QuillCommentComposer'

const MAX_REPLY_AVATARS = 3

interface QuillCommentThreadProps {
    thread: CommentWithRepliesType
    /** The reply composer mounts at the thread's end while this thread is the reply target. */
    logicProps: CommentsLogicProps
}

export function QuillCommentThread({ thread, logicProps }: QuillCommentThreadProps): JSX.Element {
    const { replyingCommentId, expandedThreadIds } = useValues(commentsLogic)
    const { setReplyingComment, setThreadExpanded } = useActions(commentsLogic)
    const { comment, replies } = thread
    const composerRef = useRef<HTMLDivElement>(null)

    // The reply target always resolves to the thread root, and it is always expanded.
    const isReplyTarget = replyingCommentId === thread.id
    const isExpanded = expandedThreadIds.has(thread.id)
    const latestReply = replies[replies.length - 1]
    const replyAuthors = replies.filter(
        (reply, index) =>
            replies.findIndex((other) => other.created_by?.id === reply.created_by?.id) === index && reply.created_by
    )

    const replySummary =
        replies.length > 0 && !isExpanded ? (
            <ThreadItemReplies
                onClick={() => setThreadExpanded(thread.id, true)}
                aria-expanded={false}
                data-attr="comment-thread-toggle"
            >
                <AvatarGroup size="xs">
                    {replyAuthors.slice(0, MAX_REPLY_AVATARS).map((reply) => (
                        <QuillCommentAvatar key={reply.id} comment={reply} size="xs" />
                    ))}
                </AvatarGroup>
                <ThreadItemRepliesLabel>{pluralize(replies.length, 'reply', 'replies')}</ThreadItemRepliesLabel>
                {latestReply?.created_at && (
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

    const collapse = (): void => {
        if (isReplyTarget) {
            setReplyingComment(null)
        }
        setThreadExpanded(thread.id, false)
    }

    return (
        <section
            aria-label="Comment thread"
            className={cn(
                'flex flex-col rounded-lg border border-border bg-card text-card-foreground',
                isReplyTarget && 'border-ring'
            )}
            data-attr="discussions-thread"
        >
            <ThreadItemGroup className="p-1">
                {comment ? (
                    <QuillComment comment={comment}>{replySummary}</QuillComment>
                ) : (
                    <div className="flex flex-col gap-1 px-2 py-1.5">
                        <Text size="xs" variant="muted" render={<span className="m-0 italic" />}>
                            This comment was deleted
                        </Text>
                        {replySummary}
                    </div>
                )}
                {isExpanded && replies.map((reply) => <QuillComment key={reply.id} comment={reply} />)}
            </ThreadItemGroup>
            {isExpanded && replies.length > 0 && !isReplyTarget && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-2 py-1">
                    <Button variant="link-muted" size="sm" onClick={collapse} data-attr="comment-thread-collapse">
                        Hide replies
                    </Button>
                    <Button size="sm" onClick={() => setReplyingComment(thread.id)} data-attr="comment-thread-reply">
                        Reply
                    </Button>
                </div>
            )}
            {isReplyTarget && (
                <div ref={composerRef} className="border-t border-border p-2">
                    <QuillCommentComposer logicProps={logicProps} />
                </div>
            )}
        </section>
    )
}
