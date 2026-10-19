import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { ThreadItemAction, ThreadItemGroup } from '@posthog/quill'

import { CanvasCommentEntry } from './CanvasCommentEntry'
import { CanvasCommentReplyForm } from './CanvasCommentReplyForm'
import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThread, isThreadStateComment } from './canvasCommentThreads'

/** One comment thread over the canvas: its comments and a reply box. */
export function CanvasCommentThreadCard({ thread }: { thread: CanvasCommentThread }): JSX.Element {
    const { writing } = useValues(canvasCommentsLogic)
    const { setThreadResolved } = useActions(canvasCommentsLogic)
    const { anchor } = thread.context
    const replies = thread.replies.filter((reply) => !isThreadStateComment(reply))

    const resolveLabel = thread.resolved ? 'Reopen thread' : 'Resolve thread'
    const resolveAction = (
        <ThreadItemAction
            label={resolveLabel}
            variant="default"
            loading={writing === thread.root.id}
            disabled={!!writing && writing !== thread.root.id}
            onClick={() => setThreadResolved(thread.root.id, !thread.resolved)}
            data-attr={thread.resolved ? 'canvas-comment-reopen' : 'canvas-comment-resolve'}
        >
            {thread.resolved ? <IconRefresh /> : <IconCheck />}
        </ThreadItemAction>
    )

    return (
        <section
            aria-label={anchor ? `Comments on "${anchor.quote}"` : 'Comment thread'}
            className="flex min-h-0 flex-col"
            data-attr="canvas-comment-thread"
        >
            <div className="min-h-0 flex-1 overflow-y-auto py-2">
                <ThreadItemGroup>
                    <CanvasCommentEntry comment={thread.root} actions={resolveAction} />
                    {replies.map((reply) => (
                        <CanvasCommentEntry key={reply.id} comment={reply} />
                    ))}
                </ThreadItemGroup>
            </div>
            {!thread.resolved && (
                <div className="border-t border-border p-2">
                    <CanvasCommentReplyForm rootId={thread.root.id} />
                </div>
            )}
        </section>
    )
}
