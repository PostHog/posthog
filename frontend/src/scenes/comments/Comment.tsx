import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheck, IconEllipsis, IconPencil, IconShare } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTextAreaMarkdown, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { CommentType } from '~/types'

import { CommentWithRepliesType, commentsLogic } from './commentsLogic'

export type CommentProps = {
    commentWithReplies: CommentWithRepliesType
}

const Comment = ({ comment }: { comment: CommentType }): JSX.Element => {
    const { editingComment, commentsLoading, replyingCommentId } = useValues(commentsLogic)
    const { deleteComment, setEditingComment, persistEditedComment, setReplyingComment } = useActions(commentsLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    const isHighlighted = replyingCommentId === comment.id || editingComment?.id === comment.id

    useEffect(() => {
        if (isHighlighted) {
            ref.current?.scrollIntoView()
        }
    }, [isHighlighted])

    return (
        <div
            ref={ref}
            className={clsx('Comment bg-surface-primary rounded-lg border', isHighlighted && 'border-accent')}
            data-comment-id={comment.id}
        >
            <div className="flex flex-1 justify-start gap-2 p-2">
                <ProfilePicture className="mt-1" size="xl" user={comment.created_by} />

                <div className="flex flex-1 flex-col">
                    <div className="flex items-center gap-2">
                        <span className="flex-1 font-semibold">{comment.created_by?.first_name ?? 'Unknown user'}</span>
                        {comment.created_at ? (
                            <span className="text-xs">
                                <TZLabel time={comment.created_at} />
                            </span>
                        ) : null}

                        <LemonMenu
                            items={[
                                {
                                    icon: <IconShare />,
                                    label: 'Reply',
                                    onClick: () => setReplyingComment(comment.source_comment ?? comment.id),
                                },
                                {
                                    icon: <IconPencil />,
                                    label: 'Edit',
                                    onClick: () => setEditingComment(comment),
                                },
                                {
                                    icon: <IconCheck />,
                                    label: 'Delete',
                                    onClick: () => deleteComment(comment),
                                    // disabledReason: "Only admins can archive other peoples comments"
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="xsmall" />
                        </LemonMenu>
                    </div>
                    <LemonMarkdown lowKeyHeadings>{comment.content}</LemonMarkdown>
                    {comment.version ? <span className="text-secondary text-xs italic">(edited)</span> : null}
                </div>
            </div>

            {editingComment?.id === comment.id ? (
                <div className="deprecated-space-y-2 border-t p-2">
                    <LemonTextAreaMarkdown
                        data-attr="comment-composer"
                        placeholder="Edit comment"
                        value={editingComment.content}
                        onChange={(value) => setEditingComment({ ...editingComment, content: value })}
                        disabled={commentsLoading}
                        onPressCmdEnter={persistEditedComment}
                    />
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex-1" />
                        <LemonButton
                            type="secondary"
                            onClick={() => setEditingComment(null)}
                            disabled={commentsLoading}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={persistEditedComment}
                            disabledReason={
                                !editingComment.content ? 'No message' : commentsLoading ? 'Saving...' : null
                            }
                            sideIcon={<KeyboardShortcut command enter />}
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </div>
            ) : null}
        </div>
    )
}

export const CommentWithReplies = ({ commentWithReplies }: CommentProps): JSX.Element => {
    const { comment, replies } = commentWithReplies

    // TODO: Permissions

    return (
        <div className="deprecated-space-y-2 relative">
            {comment ? (
                <Comment comment={comment} />
            ) : (
                <div className="bg-surface-primary text-secondary rounded border border-dashed p-2 font-semibold italic">
                    Deleted comment
                </div>
            )}

            <div className="deprecated-space-y-2 pl-8">
                {replies?.map((x) => (
                    <CommentWithReplies
                        key={x.id}
                        commentWithReplies={{
                            id: x.id,
                            comment: x,
                            replies: [],
                        }}
                    />
                ))}
            </div>
        </div>
    )
}
