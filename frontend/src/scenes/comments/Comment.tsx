import { generateText } from '@tiptap/core'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconChevronRight, IconEllipsis, IconEye, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, LemonTag, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import {
    DEFAULT_EXTENSIONS,
    LemonRichContentEditor,
    serializationOptions,
} from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { CommentType } from '~/types'

import { CommentComposer } from './CommentComposer'
import { CommentsLogicProps, CommentWithRepliesType, commentsLogic } from './commentsLogic'
import { getRecordingLinkInfo, isViewingRecording } from './commentUtils'

export type CommentProps = {
    commentWithReplies: CommentWithRepliesType
    /** Provided only for top-level threads - enables the inline reply composer */
    composerLogicProps?: CommentsLogicProps
}

const CommentBottomRow = ({ comment }: { comment: CommentType }): JSX.Element | null => {
    const { emojiReactionsByComment, isMyComment } = useValues(commentsLogic)
    const { deleteComment, sendEmojiReaction } = useActions(commentsLogic)

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

    let timeInRecordingLabel: string | null = null
    if (comment.item_context?.milliseconds_into_recording !== undefined) {
        timeInRecordingLabel = colonDelimitedDuration(comment.item_context?.milliseconds_into_recording / 1000, null)
    }

    // Keep comment cards slim: skip the whole row when there is nothing to show in it
    if (!recordingLinkInfo && !comment.version && !Object.keys(reactions).length) {
        return null
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
                </div>
            </div>
        </div>
    )
}

const CommentEditingForm = ({ comment }: { comment: CommentType }): JSX.Element => {
    const { editingComment, commentsLoading, editingCommentRichContentEditor, isEditingCommentEmpty } =
        useValues(commentsLogic)
    const {
        setEditingComment,
        persistEditedComment,
        setEditingCommentRichContentEditor,
        onEditingCommentRichContentEditorUpdate,
    } = useActions(commentsLogic)

    return (
        <div className="deprecated-space-y-2">
            <LemonRichContentEditor
                placeholder="Edit comment"
                initialContent={comment.rich_content}
                onCreate={setEditingCommentRichContentEditor}
                onUpdate={(isEmpty) => {
                    if (editingCommentRichContentEditor && editingComment) {
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
            <div className="flex justify-end items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
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
                    size="small"
                    onClick={persistEditedComment}
                    disabledReason={isEditingCommentEmpty ? 'No message' : commentsLoading ? 'Saving...' : null}
                    sideIcon={<KeyboardShortcut command enter />}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

const CommentTopRow = ({ comment }: { comment: CommentType }): JSX.Element => {
    const { disabledReasonFor } = useValues(commentsLogic)
    const { deleteComment, setEditingComment, sendEmojiReaction } = useActions(commentsLogic)

    const isCompleted = !!comment.completed_at

    return (
        <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
                <span className="ph-no-capture flex-1 font-semibold">
                    {comment.created_by?.first_name ?? 'Unknown user'}
                </span>
                {comment.is_task ? (
                    <LemonTag size="small" type={isCompleted ? 'success' : 'warning'}>
                        {isCompleted ? 'Completed' : 'Task'}
                    </LemonTag>
                ) : null}
            </div>
            <div className="flex items-center gap-1">
                {comment.created_at ? (
                    <span className="text-xs">
                        <TZLabel time={comment.created_at} />
                    </span>
                ) : null}

                <span className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <EmojiPickerPopover
                        size="xsmall"
                        onSelect={(emoji: string): void => {
                            sendEmojiReaction(emoji, comment.id)
                        }}
                        data-attr="comment-react-button"
                    />
                </span>

                <LemonMenu
                    items={[
                        {
                            icon: <IconPencil />,
                            label: 'Edit',
                            onClick: () => setEditingComment(comment),
                        },
                        {
                            icon: <IconTrash />,
                            label: 'Delete',
                            onClick: () => deleteComment(comment),
                            disabledReason: disabledReasonFor(comment),
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
    const { editingComment, replyingCommentId, selectedCommentId, commentContexts } = useValues(commentsLogic)
    const { setSelectedComment, completeComment, reopenComment } = useActions(commentsLogic)
    const contextText = commentContexts[comment.id]
    const isInlineComment = comment.item_context?.type === 'mark'

    const ref = useRef<HTMLDivElement | null>(null)

    const isEditing = editingComment?.id === comment.id
    // The reply target wins over selection so only one comment ever reads as focused
    const isHighlighted = (replyingCommentId ?? selectedCommentId) === comment.id || isEditing
    const threadId = comment.source_comment ?? comment.id

    useEffect(() => {
        if (isHighlighted) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [isHighlighted])

    return (
        <div
            ref={ref}
            className={clsx('Comment group px-2 py-1', isHighlighted && 'bg-fill-highlight-50')}
            data-comment-id={comment.id}
            // Selection is not a visual focus: it drives the notebook mark highlight and deep links
            onClick={isEditing ? undefined : () => setSelectedComment(threadId)}
        >
            <div className="flex items-center gap-3">
                {comment.is_task ? (
                    <>
                        <Tooltip
                            title={
                                comment.completed_at
                                    ? `Completed by ${comment.completed_by?.first_name ?? 'Unknown user'}`
                                    : 'Mark as complete'
                            }
                        >
                            <span className="flex items-center scale-125 ml-1">
                                <LemonCheckbox
                                    checked={!!comment.completed_at}
                                    onChange={() =>
                                        comment.completed_at ? reopenComment(comment) : completeComment(comment)
                                    }
                                    data-attr="comment-task-checkbox"
                                />
                            </span>
                        </Tooltip>
                        <LemonDivider vertical className="self-stretch" />
                    </>
                ) : null}
                <div className="flex flex-col justify-start gap-2 flex-1 min-w-0">
                    <div className="flex-1 flex justify-start items-start gap-2">
                        <ProfilePicture size={comment.source_comment ? 'md' : 'xl'} user={comment.created_by} />

                        <div className="flex flex-col flex-1 min-w-0">
                            <CommentTopRow comment={comment} />
                            {contextText && !isEditing && isInlineComment && (
                                <div className="border-l-2 border-border pl-2 my-2">
                                    <span className="block text-muted truncate text-sm">{contextText}</span>
                                </div>
                            )}
                            {isEditing ? (
                                <CommentEditingForm comment={comment} />
                            ) : (
                                <div className={clsx(comment.completed_at && 'line-through text-secondary')}>
                                    <LemonMarkdown lowKeyHeadings>{getText(comment)}</LemonMarkdown>
                                </div>
                            )}
                        </div>
                    </div>
                    {!isEditing && <CommentBottomRow comment={comment} />}
                </div>
            </div>
        </div>
    )
}

const InlineReplyComposer = ({ logicProps }: { logicProps: CommentsLogicProps }): JSX.Element => {
    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        // In long threads the composer mounts below the fold at the thread's bottom
        ref.current?.scrollIntoView({ block: 'nearest' })
    }, [])

    return (
        <div ref={ref}>
            <CommentComposer {...logicProps} variant="inline-reply" />
        </div>
    )
}

export const CommentWithReplies = ({ commentWithReplies, composerLogicProps }: CommentProps): JSX.Element => {
    const { comment, replies } = commentWithReplies
    const { replyingCommentId, expandedThreadIds, editingComment } = useValues(commentsLogic)
    const { setReplyingComment, setThreadExpanded } = useActions(commentsLogic)

    // replyingCommentId always resolves to the thread root, so this only matches top-level threads
    const isTopLevel = !!composerLogicProps
    const isReplyTarget = isTopLevel && replyingCommentId === commentWithReplies.id
    const isExpanded = expandedThreadIds.has(commentWithReplies.id)
    const showReplies = (replies.length > 0 && isExpanded) || isReplyTarget
    const canToggle = isTopLevel && replies.length > 0 && editingComment?.id !== commentWithReplies.id

    const replyButton =
        isTopLevel && !isReplyTarget ? (
            <LemonButton
                size="xsmall"
                onClick={() => setReplyingComment(commentWithReplies.id)}
                data-attr="comment-reply-button"
            >
                Reply
            </LemonButton>
        ) : null

    // TODO: Permissions

    return (
        <div className={clsx('border rounded-lg bg-surface-primary overflow-hidden', isReplyTarget && 'border-accent')}>
            <div
                className={canToggle ? 'cursor-pointer' : undefined}
                data-attr={canToggle ? 'comment-thread-toggle' : undefined}
                onClick={
                    canToggle
                        ? (e) => {
                              // Leave clicks on inner controls and text selections alone
                              const target = e.target as HTMLElement
                              if (target.closest('button, a, label, input, textarea, [contenteditable="true"]')) {
                                  return
                              }
                              if (window.getSelection()?.toString()) {
                                  return
                              }
                              setThreadExpanded(commentWithReplies.id, !isExpanded)
                          }
                        : undefined
                }
            >
                {comment ? (
                    <Comment comment={comment} />
                ) : (
                    <div className="px-2 py-1 font-semibold italic text-secondary">Deleted comment</div>
                )}

                {replies.length > 0 ? (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="flex items-center gap-1 px-2 py-1 text-xs text-secondary">
                            <IconChevronRight
                                className={clsx('size-3 shrink-0 transition-transform', isExpanded && 'rotate-90')}
                            />
                            <span>{replies.length === 1 ? '1 reply' : `${replies.length} replies`}</span>
                            {/* While the thread is open the reply affordance lives at its bottom instead */}
                            {!showReplies ? <div className="ml-auto">{replyButton}</div> : null}
                        </div>
                    </>
                ) : null}
            </div>

            {showReplies ? replies.map((reply) => <Comment key={reply.id} comment={reply} />) : null}

            {isReplyTarget && composerLogicProps ? (
                <>
                    <LemonDivider className="my-0" />
                    <div className="p-2">
                        <InlineReplyComposer logicProps={composerLogicProps} />
                    </div>
                </>
            ) : replyButton && (replies.length === 0 || showReplies) ? (
                <>
                    <LemonDivider className="my-0" />
                    <div className="flex justify-end px-2 py-1">{replyButton}</div>
                </>
            ) : null}
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
