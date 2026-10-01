import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { Badge, Text, ThreadItemAction, ThreadItemGroup, cn } from '@posthog/quill'

import { canvasHistoryLogic } from '../../history/canvasHistoryLogic'
import { CanvasCommentEntry } from './CanvasCommentEntry'
import { CanvasCommentReplyForm } from './CanvasCommentReplyForm'
import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThread, isThreadStateComment } from './canvasCommentThreads'

/** One comment thread: the text it is about, its comments, and a reply box. */
export function CanvasCommentThreadCard({ thread }: { thread: CanvasCommentThread }): JSX.Element {
    const { activeThreadId, writing } = useValues(canvasCommentsLogic)
    const { setActiveThread, setThreadResolved } = useActions(canvasCommentsLogic)
    const { versionLabels, displayedVersionId } = useValues(canvasHistoryLogic)
    const { setBrowseVersion } = useActions(canvasHistoryLogic)
    const ref = useRef<HTMLElement>(null)
    const active = activeThreadId === thread.root.id
    const { anchor, canvasVersionId } = thread.context
    const versionLabel = canvasVersionId ? versionLabels[canvasVersionId] : null
    const onOtherVersion = !!canvasVersionId && canvasVersionId !== displayedVersionId
    const replies = thread.replies.filter((reply) => !isThreadStateComment(reply))

    // A click on the anchor in the canvas brings its thread into view.
    useEffect(() => {
        if (active) {
            ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [active])

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
            ref={ref}
            aria-label={anchor ? `Comments on "${anchor.quote}"` : 'Comment thread'}
            data-selected={active || undefined}
            className={cn('flex flex-col gap-1 rounded-md py-2', active && 'bg-fill-selected')}
            data-attr="canvas-comment-thread"
        >
            {(anchor || versionLabel || thread.resolved) && (
                <div className="flex min-w-0 flex-col gap-1 px-2">
                    {anchor && (
                        <button
                            type="button"
                            className="min-w-0 cursor-pointer rounded-sm border-l-2 border-primary pl-2 text-left"
                            onClick={() => {
                                setActiveThread(active ? null : thread.root.id)
                                if (onOtherVersion && canvasVersionId) {
                                    setBrowseVersion(canvasVersionId)
                                }
                            }}
                            aria-pressed={active}
                            data-attr="canvas-comment-thread-anchor"
                        >
                            <Text size="xs" variant="muted" className="line-clamp-2 italic">
                                {anchor.quote}
                            </Text>
                        </button>
                    )}
                    {(versionLabel || thread.resolved) && (
                        <div className="flex min-w-0 flex-wrap items-center gap-1">
                            {thread.resolved && <Badge variant="completed">Resolved</Badge>}
                            {versionLabel && (
                                <Text size="xxs" variant="muted">
                                    {onOtherVersion ? `Left on ${versionLabel}` : `On ${versionLabel}`}
                                </Text>
                            )}
                        </div>
                    )}
                </div>
            )}
            <ThreadItemGroup>
                <CanvasCommentEntry comment={thread.root} actions={resolveAction} />
                {replies.map((reply) => (
                    <CanvasCommentEntry key={reply.id} comment={reply} />
                ))}
            </ThreadItemGroup>
            {!thread.resolved && (
                <div className="px-2">
                    <CanvasCommentReplyForm rootId={thread.root.id} />
                </div>
            )}
        </section>
    )
}
