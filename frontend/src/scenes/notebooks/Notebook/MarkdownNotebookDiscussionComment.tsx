import { useValues } from 'kea'
import { KeyboardEvent, useEffect, useRef, useState } from 'react'

import { IconSend, IconTrash } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import {
    NotebookComponentBlockNode,
    NotebookComponentRenderProps,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'
import { userLogic } from 'scenes/userLogic'

/**
 * One human reply inside a `<Comment ref="…" replies={[…]} />` tag. Replies live in the
 * markdown itself, keyed by `id` so concurrent replies from different people merge
 * instead of clobbering each other (see mergeIdKeyedArrayPropValues in collaboration.ts).
 */
export type NotebookCommentReply = {
    id: string
    text: string
    author?: string
    authorId?: number
    at?: string
}

export function getNotebookCommentReplies(value: NotebookPropValue | undefined): NotebookCommentReply[] {
    if (!Array.isArray(value)) {
        return []
    }

    return value.flatMap((entry): NotebookCommentReply[] => {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
            return []
        }
        const { id, text, author, authorId, at } = entry as Record<string, NotebookPropValue>
        if (typeof id !== 'string' || typeof text !== 'string') {
            return []
        }
        return [
            {
                id,
                text,
                author: typeof author === 'string' ? author : undefined,
                authorId: typeof authorId === 'number' ? authorId : undefined,
                at: typeof at === 'string' ? at : undefined,
            },
        ]
    })
}

export function getNotebookDiscussionCommentTitle(node: NotebookComponentBlockNode): string | null {
    const firstReply = getNotebookCommentReplies(node.props.replies)[0]
    return firstReply ? firstReply.text : 'Comment thread'
}

/**
 * A Google Docs-style inline comment thread anchored to highlighted text: the thread hangs
 * in the right margin and the `<ref>` tag it points at gets a persistent highlight.
 * Deleting the thread also unwraps the highlight (handled by the editor); removing the
 * highlight leaves the thread in place — it holds people's replies and is deleted
 * separately.
 */
export function NotebookDiscussionComment({
    node,
    mode,
    updateProps,
    deleteNode,
}: NotebookComponentRenderProps): JSX.Element {
    const { user } = useValues(userLogic)
    const replies = getNotebookCommentReplies(node.props.replies)
    const refId = typeof node.props.ref === 'string' ? node.props.ref : null
    const [draft, setDraft] = useState('')
    const [isHovered, setIsHovered] = useState(false)
    const repliesRef = useRef<HTMLDivElement | null>(null)
    const isEditable = mode === 'edit'
    const draftText = draft.trim()

    // Light up the anchored highlight while the cursor is over the thread.
    useEffect(() => {
        if (!refId || !isHovered || typeof document === 'undefined') {
            return
        }

        const highlightedElements = Array.from(document.querySelectorAll(`[data-notebook-ref="${CSS.escape(refId)}"]`))
        highlightedElements.forEach((element) => element.classList.add('MarkdownNotebook__ref--active'))
        return () => {
            highlightedElements.forEach((element) => element.classList.remove('MarkdownNotebook__ref--active'))
        }
    }, [refId, isHovered])

    // The replies list is height-capped; new replies should land in view, not below the fold.
    useEffect(() => {
        const element = repliesRef.current
        if (element) {
            element.scrollTop = element.scrollHeight
        }
    }, [replies.length])

    const submitReply = (): void => {
        if (!draftText || !isEditable) {
            return
        }

        const reply: NotebookCommentReply = {
            id: uuid(),
            text: draftText,
            author: user?.first_name || user?.email || undefined,
            authorId: user?.id,
            at: dayjs.utc().toISOString(),
        }
        updateProps({ replies: [...replies, reply] })
        setDraft('')
    }

    const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
        event.stopPropagation()

        if (event.key === 'Enter' && !event.nativeEvent.isComposing && !event.shiftKey) {
            event.preventDefault()
            submitReply()
        }
    }

    return (
        <div
            className="MarkdownNotebook__discussion-comment"
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            data-attr="notebook-discussion-comment"
        >
            <div className="MarkdownNotebook__discussion-comment-replies" ref={repliesRef}>
                {replies.map((reply) => (
                    <div key={reply.id} className="MarkdownNotebook__discussion-comment-reply">
                        <ProfilePicture user={{ first_name: reply.author }} size="sm" />
                        <div className="MarkdownNotebook__discussion-comment-reply-body">
                            <div className="MarkdownNotebook__discussion-comment-reply-meta">
                                <span className="MarkdownNotebook__discussion-comment-reply-author">
                                    {reply.author ?? 'Someone'}
                                </span>
                                {reply.at ? (
                                    <span className="MarkdownNotebook__discussion-comment-reply-time">
                                        <TZLabel time={reply.at} />
                                    </span>
                                ) : null}
                            </div>
                            <div className="MarkdownNotebook__discussion-comment-reply-text">{reply.text}</div>
                        </div>
                    </div>
                ))}
                {!replies.length && !isEditable ? (
                    <div className="MarkdownNotebook__discussion-comment-empty">No replies yet</div>
                ) : null}
            </div>
            {isEditable ? (
                <div className="MarkdownNotebook__discussion-comment-composer">
                    <div className="flex flex-col rounded input-like">
                        <textarea
                            className="LemonTextArea MarkdownNotebook__discussion-comment-input w-full rounded"
                            value={draft}
                            onChange={(event) => {
                                event.stopPropagation()
                                setDraft(event.currentTarget.value)
                            }}
                            onKeyDown={handleComposerKeyDown}
                            placeholder={replies.length ? 'Reply...' : 'Comment...'}
                            rows={1}
                            autoFocus={wasNotebookNodeJustInserted(node.id)}
                            data-attr="notebook-discussion-comment-input"
                        />
                    </div>
                    <div className="MarkdownNotebook__discussion-comment-actions">
                        {isEditable ? (
                            <LemonButton
                                size="xsmall"
                                icon={<IconTrash />}
                                tooltip="Delete thread"
                                aria-label="Delete thread"
                                onClick={deleteNode}
                            />
                        ) : null}
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            icon={<IconSend />}
                            onClick={submitReply}
                            disabledReason={draftText ? undefined : 'Write a reply first'}
                            aria-label="Send reply"
                        />
                    </div>
                </div>
            ) : null}
        </div>
    )
}
