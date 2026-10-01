import { IconPinFilled, IconPullRequest } from '@posthog/icons'
import { Avatar, AvatarFallback, AvatarGroup, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { PrStateEnumApi } from 'products/tasks/frontend/generated/api.schemas'
import { pullRequestLinkLabel, pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'
import { TaskPullRequest } from 'products/tasks/frontend/spaces/taskPullRequests'

// The ring keeps two overlapping badges apart, so they do not read as one glyph.
const BADGE_CLASS = 'ring-1 ring-border'

interface TodaySessionBadgesProps {
    pullRequest: TaskPullRequest | null
    pullRequestState: PrStateEnumApi | null | undefined
    pinned: boolean
}

/** A session row's trailing stack, like PostHog Desktop: the pin, then the pull request colored by its state. */
export function TodaySessionBadges({ pullRequest, pullRequestState, pinned }: TodaySessionBadgesProps): JSX.Element {
    const known = pullRequestStateMeta(pullRequestState)
    return (
        <AvatarGroup stacked reverse size="xs" className="shrink-0">
            {pinned && (
                <Tooltip>
                    <TooltipTrigger
                        delay={200}
                        render={<Avatar size="xs" role="img" aria-label="Pinned" className={BADGE_CLASS} />}
                    >
                        <AvatarFallback className="bg-transparent">
                            <IconPinFilled className="size-2.5 text-muted-foreground" />
                        </AvatarFallback>
                    </TooltipTrigger>
                    <TooltipContent>Pinned</TooltipContent>
                </Tooltip>
            )}
            {pullRequest && (
                <Tooltip>
                    <TooltipTrigger
                        delay={200}
                        render={
                            <Avatar
                                size="xs"
                                render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                                aria-label={pullRequestLinkLabel(pullRequest, pullRequestState)}
                                data-attr="today-pr-chip-sidebar"
                                className={BADGE_CLASS}
                            />
                        }
                    >
                        <AvatarFallback className="bg-transparent">
                            <IconPullRequest
                                className={cn('size-2.5', known?.iconClassName ?? 'text-muted-foreground')}
                            />
                        </AvatarFallback>
                    </TooltipTrigger>
                    <TooltipContent>
                        {`${known?.label ?? 'Pull request'} · ${pullRequest.repository}#${pullRequest.number}`}
                    </TooltipContent>
                </Tooltip>
            )}
        </AvatarGroup>
    )
}
