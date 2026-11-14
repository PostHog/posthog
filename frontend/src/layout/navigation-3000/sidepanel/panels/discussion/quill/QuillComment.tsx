import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useRef } from 'react'

import {
    Badge,
    Checkbox,
    Text,
    ThreadItem,
    ThreadItemAuthor,
    ThreadItemBody,
    ThreadItemContent,
    ThreadItemGutter,
    ThreadItemHeader,
    ThreadItemTimestamp,
    cn,
} from '@posthog/quill'

import { commentsLogic } from 'lib/components/Comments/commentsLogic'
import { getCommentAuthorName, getCommentText } from 'lib/components/Comments/commentUtils'
import { QuillMemberHoverCard } from 'lib/components/QuillMemberHoverCard/QuillMemberHoverCard'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { CommentType } from '~/types'

import { QuillCommentActions } from './QuillCommentActions'
import { QuillCommentAvatar } from './QuillCommentAvatar'
import { QuillCommentEditForm } from './QuillCommentEditForm'
import { QuillCommentMeta } from './QuillCommentMeta'
import { QuillCommentReactions } from './QuillCommentReactions'

interface QuillCommentProps {
    comment: CommentType
    /** A follow-up from the same author moments later drops its avatar and header, as in a chat feed. */
    isContinuation?: boolean
    /** Rendered at the end of the content column, such as a thread's reply summary. */
    children?: ReactNode
}

export function QuillComment({ comment, isContinuation = false, children }: QuillCommentProps): JSX.Element {
    const { editingComment, selectedCommentId, commentContexts } = useValues(commentsLogic)
    const { setSelectedComment, completeComment, reopenComment } = useActions(commentsLogic)
    const ref = useRef<HTMLElement | null>(null)

    const isEditing = editingComment?.id === comment.id
    const isHighlighted = selectedCommentId === comment.id || isEditing
    const isCompleted = !!comment.completed_at
    const fromSlack = !!comment.item_context?.from_slack
    // A comment anchored to text, such as a notebook mark, quotes that text above its body.
    const quotedText = comment.item_context?.type === 'mark' ? commentContexts[comment.id] : null
    // Rendering Markdown from tiptap JSON isn't free, so unrelated rerenders skip it.
    const text = useMemo(() => getCommentText(comment), [comment])

    useEffect(() => {
        if (isHighlighted) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [isHighlighted])

    return (
        <ThreadItem
            ref={ref}
            data-comment-id={comment.id}
            className={cn(isHighlighted && 'bg-fill-selected')}
            // Selection isn't a visual focus. It drives the notebook mark highlight and deep links.
            onClick={isEditing ? undefined : () => setSelectedComment(comment.source_comment ?? comment.id)}
        >
            <ThreadItemGutter>
                {isContinuation ? (
                    comment.created_at && (
                        <ThreadItemTimestamp dateTime={comment.created_at} className="text-xs leading-5">
                            <TZLabel
                                time={comment.created_at}
                                timestampStyle="absolute"
                                formatDate=""
                                formatTime="h:mm"
                            />
                        </ThreadItemTimestamp>
                    )
                ) : (
                    <QuillMemberHoverCard user={comment.created_by}>
                        <QuillCommentAvatar comment={comment} size="default" />
                    </QuillMemberHoverCard>
                )}
            </ThreadItemGutter>
            <ThreadItemContent>
                {isContinuation ? (
                    <span className="sr-only">{getCommentAuthorName(comment)}</span>
                ) : (
                    <ThreadItemHeader className="flex-wrap">
                        <QuillMemberHoverCard user={comment.created_by}>
                            <ThreadItemAuthor className="ph-no-capture truncate">
                                {getCommentAuthorName(comment)}
                            </ThreadItemAuthor>
                        </QuillMemberHoverCard>
                        {fromSlack && <Badge>Via Slack</Badge>}
                        {comment.is_task && (
                            <Badge variant={isCompleted ? 'completed' : 'warning'} className="ph-no-capture">
                                {isCompleted
                                    ? `Completed by ${comment.completed_by?.first_name ?? 'Unknown user'}`
                                    : 'Task'}
                            </Badge>
                        )}
                        {comment.created_at && (
                            <ThreadItemTimestamp dateTime={comment.created_at}>
                                <TZLabel time={comment.created_at} />
                            </ThreadItemTimestamp>
                        )}
                    </ThreadItemHeader>
                )}
                {quotedText && !isEditing && (
                    <Text
                        size="xs"
                        variant="muted"
                        className="truncate border-l-2 border-border pl-2"
                        render={<span className="m-0 my-1 block" />}
                    >
                        {quotedText}
                    </Text>
                )}
                {isEditing ? (
                    <QuillCommentEditForm comment={comment} />
                ) : (
                    <ThreadItemBody className="flex items-start gap-2">
                        {comment.is_task && (
                            <Checkbox
                                className="mt-0.5"
                                checked={isCompleted}
                                onCheckedChange={() =>
                                    isCompleted ? reopenComment(comment) : completeComment(comment)
                                }
                                aria-label={isCompleted ? 'Reopen task' : 'Mark task as complete'}
                                data-attr="comment-task-checkbox"
                            />
                        )}
                        <LemonMarkdown
                            lowKeyHeadings
                            disableImages
                            className={cn('min-w-0 flex-1', isCompleted && 'text-muted-foreground line-through')}
                        >
                            {text}
                        </LemonMarkdown>
                    </ThreadItemBody>
                )}
                {!isEditing && <QuillCommentReactions comment={comment} />}
                {!isEditing && <QuillCommentMeta comment={comment} />}
                {children}
            </ThreadItemContent>
            {!isEditing && <QuillCommentActions comment={comment} />}
        </ThreadItem>
    )
}
