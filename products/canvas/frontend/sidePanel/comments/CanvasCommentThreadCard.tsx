import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh, IconX } from '@posthog/icons'
import { Badge, Button, Text, ThreadItemAction, ThreadItemGroup } from '@posthog/quill'

import { canvasHistoryLogic } from '../../history/canvasHistoryLogic'
import { CanvasCommentEntry } from './CanvasCommentEntry'
import { CanvasCommentReplyForm } from './CanvasCommentReplyForm'
import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThread, isThreadStateComment } from './canvasCommentThreads'

/** One comment thread over the canvas: the text it is about, its comments, and a reply box. */
export function CanvasCommentThreadCard({ thread }: { thread: CanvasCommentThread }): JSX.Element {
    const { writing } = useValues(canvasCommentsLogic)
    const { setActiveThread, setThreadResolved } = useActions(canvasCommentsLogic)
    const { versionLabels, displayedVersionId } = useValues(canvasHistoryLogic)
    const { setBrowseVersion } = useActions(canvasHistoryLogic)
    const { anchor, canvasVersionId } = thread.context
    const versionLabel = canvasVersionId ? versionLabels[canvasVersionId] : null
    const onOtherVersion = !!canvasVersionId && canvasVersionId !== displayedVersionId
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
            <div className="flex min-w-0 items-start gap-2 border-b border-border py-2 pr-1 pl-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    {anchor ? (
                        <Text size="xs" variant="muted" className="line-clamp-2 border-l-2 border-primary pl-2 italic">
                            {anchor.quote}
                        </Text>
                    ) : (
                        <Text size="xs" variant="muted">
                            Comment
                        </Text>
                    )}
                    {(versionLabel || thread.resolved) && (
                        <div className="flex min-w-0 flex-wrap items-center gap-1">
                            {thread.resolved && <Badge variant="completed">Resolved</Badge>}
                            {versionLabel && (
                                <Text size="xxs" variant="muted">
                                    {onOtherVersion ? `Left on ${versionLabel}` : `On ${versionLabel}`}
                                </Text>
                            )}
                            {onOtherVersion && canvasVersionId && (
                                <Button
                                    size="xs"
                                    variant="link-muted"
                                    onClick={() => setBrowseVersion(canvasVersionId)}
                                    data-attr="canvas-comment-thread-show-version"
                                >
                                    Show that version
                                </Button>
                            )}
                        </div>
                    )}
                </div>
                <Button
                    size="icon-sm"
                    variant="default"
                    aria-label="Close comment"
                    onClick={() => setActiveThread(null)}
                    data-attr="canvas-comment-thread-close"
                >
                    <IconX />
                </Button>
            </div>
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
