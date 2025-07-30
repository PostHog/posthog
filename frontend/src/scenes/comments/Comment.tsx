import { IconCheck, IconEllipsis, IconPencil, IconShare } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTextAreaMarkdown, ProfilePicture } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { useEffect, useRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { CommentType } from '~/types'

import { commentsLogic, CommentWithRepliesType } from './commentsLogic'
import { renderToReactElement } from '@tiptap/static-renderer'

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
            className={clsx('Comment border rounded-lg bg-surface-primary', isHighlighted && 'border-accent')}
            data-comment-id={comment.id}
        >
            <div className="flex-1 flex justify-start p-2 gap-2">
                <ProfilePicture className="mt-1" size="xl" user={comment.created_by} />

                <div className="flex flex-col flex-1">
                    <div className="flex items-center gap-2">
                        <span className="flex-1 font-semibold ">
                            {comment.created_by?.first_name ?? 'Unknown user'}
                        </span>
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
                    {comment.content ? (
                        <LemonMarkdown lowKeyHeadings>{comment.content}</LemonMarkdown>
                    ) : comment.rich_content ? (
                        renderToReactElement({ content: comment.rich_content, extensions: [] })
                    ) : null}
                    {comment.version ? <span className="text-xs text-secondary italic">(edited)</span> : null}
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
                    <div className="flex justify-between items-center gap-2">
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
        <div className="relative deprecated-space-y-2">
            {comment ? (
                <Comment comment={comment} />
            ) : (
                <div className="border rounded border-dashed p-2 font-semibold italic bg-surface-primary text-secondary">
                    Deleted comment
                </div>
            )}

            <div className="pl-8 deprecated-space-y-2">
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
