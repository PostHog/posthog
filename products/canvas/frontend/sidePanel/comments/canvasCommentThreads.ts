import type { CommentType } from '~/types'

import type { CanvasCommentHighlight, CanvasRect, CanvasTextSelection } from '../../host/canvasProtocol'

// Canvas comments are ordinary PostHog comments with scope "canvas" and the canvas id as
// item_id. The item_context shape is shared with PostHog Desktop, which writes the same
// rows, so both hosts read each other's threads and highlights.

// pinned: comment scope for canvases, shared with PostHog Desktop and the comments API
export const CANVAS_COMMENT_SCOPE = 'canvas'
// pinned: the most highlights the canvas runtime accepts in one message
const MAX_CANVAS_COMMENT_HIGHLIGHTS = 500
const MAX_CANVAS_COMMENT_HIGHLIGHT_TEXT_LENGTH = 100_000

export type CanvasTextAnchor = CanvasCommentHighlight['anchor']

export interface CanvasCommentContext {
    anchor: CanvasTextAnchor | null
    threadState: 'resolved' | 'open' | null
    /** The source version on screen when the comment was written. */
    canvasVersionId: string | null
}

export interface CanvasCommentThread {
    root: CommentType
    replies: CommentType[]
    resolved: boolean
    context: CanvasCommentContext
}

function readTextAnchor(value: unknown): CanvasTextAnchor | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    const anchor = value as Record<string, unknown>
    const { quote, prefix, suffix, start, end } = anchor
    if (
        anchor.kind !== 'text' ||
        typeof quote !== 'string' ||
        !quote ||
        typeof prefix !== 'string' ||
        typeof suffix !== 'string' ||
        typeof start !== 'number' ||
        typeof end !== 'number' ||
        !Number.isInteger(start) ||
        !Number.isInteger(end) ||
        start < 0 ||
        end <= start
    ) {
        return null
    }
    return { kind: 'text', quote, prefix, suffix, start, end }
}

export function readCanvasCommentContext(comment: Pick<CommentType, 'item_context'>): CanvasCommentContext {
    const context = comment.item_context ?? {}
    const threadState =
        context.threadState === 'resolved' || context.threadState === 'open' ? context.threadState : null
    return {
        anchor: readTextAnchor(context.anchor),
        threadState,
        canvasVersionId:
            typeof context.canvasVersionId === 'string' && context.canvasVersionId ? context.canvasVersionId : null,
    }
}

/** A reply that records a resolve or reopen, rather than something a person wrote. */
export function isThreadStateComment(comment: Pick<CommentType, 'item_context'>): boolean {
    return readCanvasCommentContext(comment).threadState !== null
}

function bySentAt(a: CommentType, b: CommentType): number {
    return a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)
}

function isThreadResolved(root: CommentType, replies: CommentType[]): boolean {
    // The newest resolve or reopen reply wins. A thread without one follows the root's completion.
    const latestState = replies
        .map((reply) => readCanvasCommentContext(reply).threadState)
        .filter((state): state is 'resolved' | 'open' => state !== null)
        .at(-1)
    return latestState ? latestState === 'resolved' : !!root.completed_at
}

/** Groups a flat comment list into threads, oldest root first, replies oldest first. */
export function buildCanvasCommentThreads(comments: readonly CommentType[]): CanvasCommentThread[] {
    const roots: CommentType[] = []
    const repliesByRoot = new Map<string, CommentType[]>()
    for (const comment of comments) {
        if (comment.deleted) {
            continue
        }
        if (!comment.source_comment) {
            roots.push(comment)
            continue
        }
        const replies = repliesByRoot.get(comment.source_comment) ?? []
        replies.push(comment)
        repliesByRoot.set(comment.source_comment, replies)
    }
    return roots.sort(bySentAt).map((root) => {
        const replies = (repliesByRoot.get(root.id) ?? []).sort(bySentAt)
        return { root, replies, resolved: isThreadResolved(root, replies), context: readCanvasCommentContext(root) }
    })
}

/**
 * The highlights to draw in the frame: open text-anchored threads written on the version on
 * screen (or on no recorded version), capped at what the canvas runtime accepts.
 */
export function canvasCommentHighlights(
    threads: readonly CanvasCommentThread[],
    displayedVersionId: string | null,
    activeThreadId: string | null
): CanvasCommentHighlight[] {
    const highlights: CanvasCommentHighlight[] = []
    let textLength = 0
    for (const thread of threads) {
        const { anchor, canvasVersionId } = thread.context
        if (thread.resolved || !anchor || (canvasVersionId && canvasVersionId !== displayedVersionId)) {
            continue
        }
        textLength += anchor.quote.length + anchor.prefix.length + anchor.suffix.length
        if (
            highlights.length >= MAX_CANVAS_COMMENT_HIGHLIGHTS ||
            textLength > MAX_CANVAS_COMMENT_HIGHLIGHT_TEXT_LENGTH
        ) {
            break
        }
        highlights.push({ id: thread.root.id, active: thread.root.id === activeThreadId, anchor })
    }
    return highlights
}

export function translateCanvasRect(rect: CanvasRect, frame: Pick<DOMRect, 'left' | 'top'> | null): CanvasRect {
    const left = frame?.left ?? 0
    const top = frame?.top ?? 0
    return {
        top: rect.top + top,
        right: rect.right + left,
        bottom: rect.bottom + top,
        left: rect.left + left,
    }
}

/** Moves a selection rect from the frame's coordinates into the page's, so the host can anchor UI to it. */
export function translateCanvasTextSelection(
    selection: CanvasTextSelection,
    frame: Pick<DOMRect, 'left' | 'top'> | null
): CanvasTextSelection {
    return { ...selection, rect: translateCanvasRect(selection.rect, frame) }
}

/** The anchor stored on a comment made from a selection. */
export function canvasTextAnchor(selection: CanvasTextSelection): CanvasTextAnchor {
    return {
        kind: 'text',
        quote: selection.quote,
        prefix: '',
        suffix: '',
        start: 0,
        end: selection.quote.length,
    }
}
