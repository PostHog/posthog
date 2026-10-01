import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { Badge, Button, Text } from '@posthog/quill'

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
    const ref = useRef<HTMLDivElement>(null)
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

    return (
        <div
            ref={ref}
            data-selected={active || undefined}
            className="flex flex-col gap-2 rounded-md border border-border p-2 data-selected:border-primary data-selected:bg-fill-selected"
            data-attr="canvas-comment-thread"
        >
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                {anchor && (
                    <button
                        type="button"
                        className="min-w-0 flex-1 cursor-pointer rounded-sm border-l-2 border-primary pl-2 text-left"
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
                {versionLabel && (
                    <Badge variant={onOtherVersion ? 'default' : 'info'}>
                        {onOtherVersion ? `On ${versionLabel}` : versionLabel}
                    </Badge>
                )}
                {thread.resolved && <Badge variant="completed">Resolved</Badge>}
            </div>
            <CanvasCommentEntry comment={thread.root} />
            {replies.map((reply) => (
                <CanvasCommentEntry key={reply.id} comment={reply} />
            ))}
            {!thread.resolved && <CanvasCommentReplyForm rootId={thread.root.id} />}
            <div className="flex justify-end">
                <Button
                    size="xs"
                    variant="default"
                    loading={writing === thread.root.id}
                    disabled={!!writing && writing !== thread.root.id}
                    onClick={() => setThreadResolved(thread.root.id, !thread.resolved)}
                    data-attr={thread.resolved ? 'canvas-comment-reopen' : 'canvas-comment-resolve'}
                >
                    {thread.resolved ? <IconRefresh /> : <IconCheck />}
                    {thread.resolved ? 'Reopen' : 'Resolve'}
                </Button>
            </div>
        </div>
    )
}
