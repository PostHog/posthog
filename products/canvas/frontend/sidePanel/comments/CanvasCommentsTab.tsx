import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconComment, IconWarning } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Label,
    Separator,
    Skeleton,
    SkeletonText,
    Switch,
    Text,
} from '@posthog/quill'

import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThreadCard } from './CanvasCommentThreadCard'

/** The Comments tab: the canvas's comment threads, newest first. */
export function CanvasCommentsTab(): JSX.Element {
    const {
        visibleThreads,
        threads,
        resolvedCount,
        showResolved,
        commentsLoadFailed,
        commentsLoading,
        commentsEnabled,
    } = useValues(canvasCommentsLogic)
    const { setShowResolved, loadComments } = useActions(canvasCommentsLogic)

    if (!commentsEnabled) {
        return (
            <Empty className="h-full border-0" data-attr="canvas-comments-unavailable">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconComment />
                    </EmptyMedia>
                    <EmptyTitle>No comments yet</EmptyTitle>
                    <EmptyDescription>Comments open once an agent has built this canvas.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
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
            <div className="flex flex-col gap-4 p-3">
                {[0, 1].map((index) => (
                    <div key={index} className="flex gap-2">
                        <Skeleton className="size-6 shrink-0 rounded-full" />
                        <SkeletonText lines={2} className="flex-1" />
                    </div>
                ))}
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
                    <div className="flex items-center gap-2">
                        <Switch
                            id="canvas-comments-show-resolved"
                            size="sm"
                            checked={showResolved}
                            onCheckedChange={(checked: boolean) => setShowResolved(checked)}
                            data-attr="canvas-comments-show-resolved"
                        />
                        <Label htmlFor="canvas-comments-show-resolved" className="text-xs">
                            {`Show resolved (${resolvedCount})`}
                        </Label>
                    </div>
                )}
            </div>
            {visibleThreads && visibleThreads.length > 0 ? (
                <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-1">
                    {visibleThreads.map((thread, index) => (
                        <Fragment key={thread.root.id}>
                            {index > 0 && <Separator />}
                            <CanvasCommentThreadCard thread={thread} />
                        </Fragment>
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
