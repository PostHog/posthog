import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconComment, IconWarning } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Skeleton,
    SkeletonText,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import { canvasHistoryLogic } from '../../history/canvasHistoryLogic'
import { canvasCommentsLogic } from './canvasCommentsLogic'
import { CanvasCommentThread, isThreadStateComment } from './canvasCommentThreads'

function ThreadRow({ thread, onOpen }: { thread: CanvasCommentThread; onOpen: () => void }): JSX.Element {
    const { versionLabels, displayedVersionId } = useValues(canvasHistoryLogic)
    const name = thread.root.created_by ? fullNameOrEmail(thread.root.created_by) : 'Someone'
    const replyCount = thread.replies.filter((reply) => !isThreadStateComment(reply)).length
    const { anchor, canvasVersionId } = thread.context
    const versionLabel =
        canvasVersionId && canvasVersionId !== displayedVersionId ? versionLabels[canvasVersionId] : null
    return (
        <button
            type="button"
            className="flex w-full min-w-0 cursor-pointer gap-2 rounded-md px-2 py-2 text-left hover:bg-fill-hover focus-visible:bg-fill-hover focus-visible:outline-none"
            onClick={onOpen}
            data-attr="canvas-comments-menu-thread"
        >
            <Avatar size="sm">
                <AvatarFallback>{name.slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex min-w-0 items-baseline gap-1.5">
                    <Text size="xs" weight="medium" className="truncate" render={<span />}>
                        {name}
                    </Text>
                    <Text size="xxs" variant="muted" className="shrink-0" render={<span />}>
                        {dayjs(thread.root.created_at).fromNow()}
                    </Text>
                </span>
                {anchor && (
                    <Text
                        size="xs"
                        variant="muted"
                        className="line-clamp-1 border-l-2 border-primary pl-1.5 italic"
                        render={<span />}
                    >
                        {anchor.quote}
                    </Text>
                )}
                <Text size="xs" className="line-clamp-2 break-words" render={<span />}>
                    {thread.root.content}
                </Text>
                {(replyCount > 0 || thread.resolved || versionLabel) && (
                    <span className="flex flex-wrap items-center gap-1">
                        {thread.resolved && <Badge variant="completed">Resolved</Badge>}
                        {versionLabel && (
                            <Text size="xxs" variant="muted" render={<span />}>
                                {`Left on ${versionLabel}`}
                            </Text>
                        )}
                        {replyCount > 0 && (
                            <Text size="xxs" variant="muted" render={<span />}>
                                {replyCount === 1 ? '1 reply' : `${replyCount} replies`}
                            </Text>
                        )}
                    </span>
                )}
            </span>
        </button>
    )
}

function MenuBody({ onOpenThread }: { onOpenThread: (thread: CanvasCommentThread) => void }): JSX.Element {
    const { visibleThreads, threads, commentsLoadFailed, commentsLoading } = useValues(canvasCommentsLogic)
    const { loadComments } = useActions(canvasCommentsLogic)

    if (!threads) {
        if (commentsLoadFailed) {
            return (
                <Empty className="border-0">
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
    if (!visibleThreads || visibleThreads.length === 0) {
        return (
            <Empty className="border-0">
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
        )
    }
    return (
        <div className="flex min-h-0 flex-col overflow-y-auto p-1">
            {visibleThreads.map((thread) => (
                <ThreadRow key={thread.root.id} thread={thread} onOpen={() => onOpenThread(thread)} />
            ))}
        </div>
    )
}

export function CanvasCommentsMenu(): JSX.Element | null {
    const { commentsEnabled, threads, resolvedCount, showResolved, displayedVersionId } = useValues(canvasCommentsLogic)
    const { setShowResolved, activateThread } = useActions(canvasCommentsLogic)
    const { setBrowseVersion } = useActions(canvasHistoryLogic)
    const [open, setOpen] = useState(false)

    if (!commentsEnabled) {
        return null
    }
    const openCount = threads?.filter((thread) => !thread.resolved).length ?? 0
    const label = openCount > 0 ? `Comments, ${openCount} open` : 'Comments'
    const openThread = (thread: CanvasCommentThread): void => {
        setOpen(false)
        const { canvasVersionId } = thread.context
        if (canvasVersionId && canvasVersionId !== displayedVersionId) {
            setBrowseVersion(canvasVersionId)
        }
        activateThread(thread.root.id, null, 'menu')
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                    <PopoverTrigger
                        render={
                            <Button
                                size={openCount > 0 ? 'sm' : 'icon-sm'}
                                variant="default"
                                aria-label={label}
                                data-attr="canvas-comments-menu"
                            />
                        }
                    >
                        <IconComment />
                        {openCount > 0 && <span className="tabular-nums">{openCount}</span>}
                    </PopoverTrigger>
                </TooltipTrigger>
                <TooltipContent>Comments</TooltipContent>
            </Tooltip>
            <PopoverContent
                align="end"
                className="max-h-[min(520px,var(--available-height))] w-80 gap-0 overflow-hidden p-0"
            >
                <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
                    <Text size="xs" weight="medium" variant="muted" render={<span />}>
                        Comments
                    </Text>
                    {resolvedCount > 0 && (
                        <div className="ml-auto flex items-center gap-2">
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
                <MenuBody onOpenThread={openThread} />
            </PopoverContent>
        </Popover>
    )
}
