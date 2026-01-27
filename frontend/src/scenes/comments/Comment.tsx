import { generateText } from '@tiptap/core'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconCheck, IconEllipsis, IconEye, IconPencil, IconShare } from '@posthog/icons'
import { LemonButton, LemonMenu, ProfilePicture } from '@posthog/lemon-ui'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import {
    DEFAULT_EXTENSIONS,
    LemonRichContentEditor,
    serializationOptions,
} from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { colonDelimitedDuration } from 'lib/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { CommentType } from '~/types'

import { getRecordingLinkInfo, isViewingRecording } from './commentUtils'
import { CommentWithRepliesType, commentsLogic } from './commentsLogic'

export type CommentProps = {
    commentWithReplies: CommentWithRepliesType
}

const CommentBottomRow = ({ comment }: { comment: CommentType }): JSX.Element => {
    const { editingComment, replyingCommentId, emojiReactionsByComment, isMyComment } = useValues(commentsLogic)
    const { deleteComment, sendEmojiReaction } = useActions(commentsLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    const isHighlighted = replyingCommentId === comment.id || editingComment?.id === comment.id
    const reactions = emojiReactionsByComment[comment.id] || {}
    const recordingLinkInfo = getRecordingLinkInfo(comment)

    const handleViewInRecording = (): void => {
        if (!recordingLinkInfo) {
            return
        }
        if (isViewingRecording(recordingLinkInfo.recordingId) && recordingLinkInfo.unixTimestampMillis) {
            router.actions.push(recordingLinkInfo.url)
        } else {
            window.location.href = recordingLinkInfo.url
        }
    }

    useEffect(() => {
        if (isHighlighted) {
            ref.current?.scrollIntoView()
        }
    }, [isHighlighted])

    let timeInRecordingLabel: string | null = null
    if (comment.item_context?.milliseconds_into_recording !== undefined) {
        timeInRecordingLabel = colonDelimitedDuration(comment.item_context?.milliseconds_into_recording / 1000, null)
    }

    return (
        <div className="flex flex-row items-center justify-between">
            <div className="flex flex-row items-center gap-1">
                {recordingLinkInfo ? (
                    <LemonButton
                        icon={<IconEye />}
                        size="xsmall"
                        type="tertiary"
                        onClick={handleViewInRecording}
                        tooltip="View in recording"
                        data-attr="view-comment-in-recording-at-timestamp"
                    >
                        {timeInRecordingLabel}
                    </LemonButton>
                ) : null}
                <span className="text-xs text-secondary italic">{comment.version ? <span>(edited)</span> : null}</span>
            </div>
            <div className="flex items-center">
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
                                            isMyComment(c) ? 'you' : (c.created_by?.first_name ?? 'Unknown user')
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
    )
}

const CommentEditingForm = ({ comment }: { comment: CommentType }): JSX.Element | null => {
    const { editingComment, commentsLoading, editingCommentRichContentEditor, isEditingCommentEmpty } =
        useValues(commentsLogic)
    const {
        setEditingComment,
        persistEditedComment,
        setEditingCommentRichContentEditor,
        onEditingCommentRichContentEditorUpdate,
    } = useActions(commentsLogic)

    return editingComment?.id === comment.id ? (
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
    ) : null
}

const CommentTopRow = ({ comment }: { comment: CommentType }): JSX.Element => {
    const {} = useValues(commentsLogic)
    const { deleteComment, setEditingComment, setReplyingComment } = useActions(commentsLogic)

    return (
        <div className="flex items-center justify-between gap-2">
            <div>
                <span className="ph-no-capture flex-1 font-semibold">
                    {comment.created_by?.first_name ?? 'Unknown user'}
                </span>
            </div>
            <div className="flex items-center gap-1">
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
        </div>
    )
}

const Comment = ({ comment }: { comment: CommentType }): JSX.Element => {
    const { editingComment, replyingCommentId } = useValues(commentsLogic)

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
            className={clsx('Comment border rounded-lg bg-surface-primary px-2 py-1', isHighlighted && 'border-accent')}
            data-comment-id={comment.id}
        >
            <div className="flex flex-col justify-start gap-2">
                <div className="flex-1 flex justify-start gap-2">
                    <ProfilePicture size="xl" user={comment.created_by} />

                    <div className="flex flex-col flex-1">
                        <CommentTopRow comment={comment} />
                        <LemonMarkdown lowKeyHeadings>{getText(comment)}</LemonMarkdown>
                    </div>
                </div>
                <CommentBottomRow comment={comment} />
            </div>

            <CommentEditingForm comment={comment} />
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
        : {
              type: 'doc',
              content: [
                  {
                      type: 'paragraph',
                      content: comment.content
                          ? [
                                {
                                    type: 'text',
                                    text: comment.content,
                                },
                            ]
                          : [],
                  },
              ],
          }

    return generateText(content, DEFAULT_EXTENSIONS, serializationOptions)
}
