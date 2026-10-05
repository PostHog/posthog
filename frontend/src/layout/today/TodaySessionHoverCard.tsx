import { useActions } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconCopy, IconPinFilled, IconPullRequest } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemSeparator,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'
import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'
import { TaskUserAvatar, taskUserName } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { TodayHoverCardFact } from './TodayHoverCardFact'
import { cardMenuParts } from './todayMenuParts'
import { TodaySessionPreview } from './todayPreviewCards'
import { TodaySessionActionItems } from './TodaySessionActionItems'
import { useTodayArchiveShortcut } from './todaySessionArchiveShortcut'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionStatusDot } from './TodaySessionStatusDot'
import { activityDetail } from './todayWorkItems'

function BranchLine({ branch }: { branch: string }): JSX.Element {
    const { copyBranchName } = useActions(todaySessionMenuLogic)
    return (
        <span className="flex min-w-0 items-center gap-1">
            <span className="truncate" title={branch}>
                {branch}
            </span>
            <Tooltip disableHoverablePopup>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon-xs"
                            aria-label="Copy branch name"
                            onClick={() => copyBranchName(branch)}
                            data-attr="today-session-hover-card-copy-branch"
                        />
                    }
                >
                    <IconCopy />
                </TooltipTrigger>
                <TooltipContent side="top" className="pointer-events-none select-none">
                    Copy branch name
                </TooltipContent>
            </Tooltip>
        </span>
    )
}

function AuthorFace({ author }: { author: TaskUserBasicInfoApi }): JSX.Element {
    const label = `Created by ${taskUserName(author)}`
    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger delay={0} render={<span role="img" aria-label={label} className="flex shrink-0" />}>
                <TaskUserAvatar user={author} />
            </TooltipTrigger>
            <TooltipContent side="top" className="pointer-events-none select-none">
                {label}
            </TooltipContent>
        </Tooltip>
    )
}

interface TodaySessionHoverCardProps {
    preview: TodaySessionPreview
    /** Closes the card once an action is chosen. */
    onAction: () => void
    /** Keeps the card open while its "File to…" menu is. */
    onSubmenuOpenChange: (open: boolean) => void
}

/**
 * A session row's hover card: what the row's marks mean in words, where the work sits, what the agent said last,
 * and the row's actions, like PostHog Desktop.
 */
export function TodaySessionHoverCard({
    preview,
    onAction,
    onSubmenuOpenChange,
}: TodaySessionHoverCardProps): JSX.Element {
    const { dot, pullRequest, author } = preview
    const { requestArchive } = useActions(todaySessionMenuLogic)
    useTodayArchiveShortcut(true, () => {
        requestArchive(preview.menu.sessionId, preview.menu.menuId, preview.menu.activeRunId)
        onAction()
    })
    const parts = useMemo(() => cardMenuParts(onAction, onSubmenuOpenChange), [onAction, onSubmenuOpenChange])
    // Base UI reports no close when the submenu unmounts with the card, which would keep the card open for good.
    useEffect(() => () => onSubmenuOpenChange(false), [onSubmenuOpenChange])
    const pullRequestState = pullRequestStateMeta(preview.pullRequestState)
    const updated = activityDetail(preview.timestamp)
    return (
        <div className="flex flex-col" data-attr="today-session-hover-card">
            <Item size="xs" className="flex-nowrap items-start">
                <ItemContent className="min-w-0 gap-2">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long URL in it would widen the card. */}
                    <ItemTitle className="flex items-start gap-2 wrap-anywhere">
                        <span className="flex h-lh w-4 shrink-0 items-center justify-center">
                            <TodaySessionStatusDot dot={dot} />
                        </span>
                        <span className="min-w-0 font-semibold">{preview.title}</span>
                    </ItemTitle>
                    <div className="flex flex-col gap-1 pl-6">
                        {preview.repository && (
                            <TodayHoverCardFact label="Repo">{preview.repository}</TodayHoverCardFact>
                        )}
                        {preview.branch && (
                            <TodayHoverCardFact label="Branch">
                                <BranchLine branch={preview.branch} />
                            </TodayHoverCardFact>
                        )}
                        {preview.spaceName && (
                            <TodayHoverCardFact label="Space">{preview.spaceName}</TodayHoverCardFact>
                        )}
                        {updated && (
                            <TodayHoverCardFact label="Updated">
                                <span title={updated.title}>{updated.text}</span>
                            </TodayHoverCardFact>
                        )}
                        {preview.source && (
                            <TodayHoverCardFact label="Source">
                                <span className="flex min-w-0 items-center gap-1.5">
                                    {preview.sourceIcon && (
                                        <span className="flex size-3 shrink-0 text-muted-foreground [&>svg]:size-full">
                                            {preview.sourceIcon}
                                        </span>
                                    )}
                                    <span className="truncate">{preview.source}</span>
                                </span>
                            </TodayHoverCardFact>
                        )}
                    </div>
                </ItemContent>
                {author && (
                    <ItemActions className="self-start">
                        <AuthorFace author={author} />
                    </ItemActions>
                )}
            </Item>
            <ItemSeparator className="my-0" />
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-1.5">
                    <Text size="xs" render={<span />}>
                        {dot.label}
                    </Text>
                    {(preview.pinned || pullRequest) && (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            {preview.pinned && (
                                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                    <IconPinFilled className="size-3 shrink-0" />
                                    Pinned
                                </span>
                            )}
                            {pullRequest && (
                                <LinkPrimitive
                                    to={pullRequest.url}
                                    target="_blank"
                                    data-attr="today-session-hover-card-pr"
                                    // Dotted at rest, so the one mark that opens something reads as a link.
                                    className="flex min-w-0 items-center gap-1 text-xs font-normal text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
                                >
                                    <IconPullRequest
                                        className={cn('size-3 shrink-0', pullRequestState?.iconClassName)}
                                    />
                                    <span className="truncate">
                                        {`${pullRequestState?.label ?? 'Pull request'} · ${pullRequest.repository}#${pullRequest.number}`}
                                    </span>
                                </LinkPrimitive>
                            )}
                        </div>
                    )}
                    {preview.message && (
                        // Three lines hold the agent's closing sentence without turning the card into a transcript.
                        <Text size="xs" variant="muted" className="line-clamp-3 leading-snug break-words">
                            {preview.message}
                        </Text>
                    )}
                </ItemContent>
            </Item>
            <ItemSeparator className="my-0" />
            <div className="flex flex-col p-1">
                <TodaySessionActionItems
                    parts={parts}
                    target={preview.menu}
                    surface="sidebar"
                    dataAttrPrefix="today-session-card"
                />
            </div>
        </div>
    )
}
