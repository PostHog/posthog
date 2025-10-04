import { generateText } from '@tiptap/core'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheck, IconClock, IconEllipsis, IconPencil, IconShare } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import {
    DEFAULT_EXTENSIONS,
    LemonRichContentEditor,
    serializationOptions,
} from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { CommentType } from '~/types'

import { CommentWithRepliesType, commentsLogic } from './commentsLogic'

export type CommentProps = {
    commentWithReplies: CommentWithRepliesType
}

const Comment = ({ comment }: { comment: CommentType }): JSX.Element => {
    const {
        editingComment,
        commentsLoading,
        replyingCommentId,
        emojiReactionsByComment,
        isMyComment,
        editingCommentRichContentEditor,
        isEditingCommentEmpty,
        propsItemContext,
    } = useValues(commentsLogic)
    const {
        deleteComment,
        setEditingComment,
        persistEditedComment,
        setReplyingComment,
        sendEmojiReaction,
        setEditingCommentRichContentEditor,
        onEditingCommentRichContentEditorUpdate,
    } = useActions(commentsLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    const isHighlighted = replyingCommentId === comment.id || editingComment?.id === comment.id
    const reactions = emojiReactionsByComment[comment.id] || {}

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
                        {comment.item_context?.time_in_recording ? (
                            <Tooltip title="Time in recording">
                                <LemonTag icon={<IconClock />} type="highlight">
                                    {(() => {
                                        if (comment.item_context.time_in_recording_ms !== undefined) {
                                            return colonDelimitedDuration(
                                                comment.item_context.time_in_recording_ms / 1000,
                                                2
                                            )
                                        }
                                        // Calculate from timestamp for old comments
                                        const recordingStartTime = propsItemContext?.recording_start_time
                                        if (recordingStartTime) {
                                            const commentTime = dayjs(comment.item_context.time_in_recording)
                                            const startTime = dayjs(recordingStartTime)
                                            const timeInRecordingMs = commentTime.diff(startTime)
                                            return colonDelimitedDuration(timeInRecordingMs / 1000, 2)
                                        }
                                        // Fallback to absolute time if no recording start time
                                        return dayjs(comment.item_context.time_in_recording).format('HH:mm:ss')
                                    })()}
                                </LemonTag>
                            </Tooltip>
                        ) : null}
                        {comment.created_at && !comment.item_context?.time_in_recording ? (
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
                    <LemonMarkdown lowKeyHeadings>{getText(comment)}</LemonMarkdown>
                    <div className="flex flex-row items-center justify-between">
                        <span className="text-xs text-secondary italic">
                            {comment.version ? <span>(edited)</span> : null}
                        </span>
                        <div data-attr="comment-reactions" className="flex items-center">
                            {Object.entries(reactions).map(([emoji, commentList]) => (
                                <LemonButton
                                    key={emoji}
                                    type="tertiary"
                                    onClick={() => {
                                        const existingCurrentUserReaction = commentList.find((emojiReaction) =>
                                            isMyComment(emojiReaction)
                                        )
                                        if (existingCurrentUserReaction) {
                                            deleteComment(existingCurrentUserReaction)
                                        } else {
                                            sendEmojiReaction(emoji, comment.id)
                                        }
                                    }}
                                    size="small"
                                    data-attr={`comment-reaction-${emoji}`}
                                    tooltip={
                                        <div className="flex flex-col gap-">
                                            <div className="text-2xl">{emoji}</div>
                                            <SentenceList
                                                listParts={commentList.map((c) =>
                                                    isMyComment(c)
                                                        ? 'you'
                                                        : (c.created_by?.first_name ?? 'Unknown user')
                                                )}
                                            />
                                        </div>
                                    }
                                >
                                    <div className="flex flex-row gap-1 items-center">
                                        <span>{emoji}</span>
                                        <span className="text-xs font-semibold">{commentList.length}</span>
                                    </div>
                                </LemonButton>
                            ))}
                            <EmojiPickerPopover
                                onSelect={(emoji: string): void => {
                                    sendEmojiReaction(emoji, comment.id)
                                }}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {editingComment?.id === comment.id ? (
                <div className="deprecated-space-y-2 border-t p-2">
                    <LemonRichContentEditor
                        placeholder="Edit comment"
                        initialContent={comment.rich_content}
                        onCreate={setEditingCommentRichContentEditor}
                        onUpdate={(isEmpty) => {
                            if (editingCommentRichContentEditor) {
                                setEditingComment({
                                    ...editingComment,
                                    rich_content: editingCommentRichContentEditor.getJSON(),
                                })
                                onEditingCommentRichContentEditorUpdate(isEmpty)
                            }
                        }}
                        onPressCmdEnter={persistEditedComment}
                        disabled={commentsLoading}
                    />
                    <div className="flex justify-between items-center gap-2">
                        <div className="flex-1" />
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setEditingComment(null)
                                setEditingCommentRichContentEditor(null)
                            }}
                            disabled={commentsLoading}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={persistEditedComment}
                            disabledReason={isEditingCommentEmpty ? 'No message' : commentsLoading ? 'Saving...' : null}
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

export function getText(comment: CommentType): string {
    // This is only temporary until all comments are backfilled to rich content
    const content = comment.rich_content
        ? comment.rich_content
        : comment.content
          ? {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            {
                                type: 'text',
                                text: comment.content,
                            },
                        ],
                    },
                ],
            }
          : {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                    },
                ],
            }

    return generateText(content, DEFAULT_EXTENSIONS, serializationOptions)
}
