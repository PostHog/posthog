import { useActions, useValues } from 'kea'

import { IconComment, IconWarning } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Switch,
    Text,
} from '@posthog/quill'

import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThreadCard } from './CanvasCommentThreadCard'

/** The Comments tab: the canvas's comment threads, newest first. */
export function CanvasCommentsTab(): JSX.Element {
    const { visibleThreads, threads, resolvedCount, showResolved, commentsLoadFailed, commentsLoading } =
        useValues(canvasCommentsLogic)
    const { setShowResolved, loadComments } = useActions(canvasCommentsLogic)

    if (!threads) {
        if (commentsLoadFailed) {
            return (
                <Empty className="h-full border-0">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconWarning />
                        </EmptyMedia>
                        <EmptyTitle>Comments didn't load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={commentsLoading}
                            onClick={() => loadComments()}
                            data-attr="canvas-comments-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div className="flex flex-col gap-3 p-3">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
                <Text size="xs" variant="muted">
                    Select text in the canvas to comment on it.
                </Text>
                {resolvedCount > 0 && (
                    <label className="flex items-center gap-1.5">
                        <Switch
                            size="sm"
                            checked={showResolved}
                            onCheckedChange={(checked: boolean) => setShowResolved(checked)}
                            data-attr="canvas-comments-show-resolved"
                        />
                        <Text size="xs">{`Show resolved (${resolvedCount})`}</Text>
                    </label>
                )}
            </div>
            {visibleThreads && visibleThreads.length > 0 ? (
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
                    {visibleThreads.map((thread) => (
                        <CanvasCommentThreadCard key={thread.root.id} thread={thread} />
                    ))}
                </div>
            ) : (
                <Empty className="min-h-0 flex-1 border-0">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconComment />
                        </EmptyMedia>
                        <EmptyTitle>{threads.length > 0 ? 'No open comments' : 'No comments yet'}</EmptyTitle>
                        <EmptyDescription>
                            Select text in the canvas, then choose Comment to start a thread.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )}
        </div>
    )
}
