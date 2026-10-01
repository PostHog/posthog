import { IconArrowRightDown, IconLaptop, IconPinFilled, IconPullRequest } from '@posthog/icons'
import { Avatar, AvatarFallback, AvatarGroup, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { IconSlack } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { PrStateEnumApi } from 'products/tasks/frontend/generated/api.schemas'
import { pullRequestLinkLabel, pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'
import { TaskPullRequest } from 'products/tasks/frontend/spaces/taskPullRequests'

import { recentSourceLabel } from './todayRecentFilters'
import { TodaySessionBadge } from './todayWorkItems'

// The ring keeps two overlapping badges apart, so they do not read as one glyph.
const BADGE_CLASS = 'ring-1 ring-border'

interface TodaySessionBadgesProps {
    badges: TodaySessionBadge[]
    pullRequestState: PrStateEnumApi | null | undefined
    pinned: boolean
}

/** A session row's trailing stack, like PostHog Desktop: the pin, the source, then the pull request colored by its state. */
export function TodaySessionBadges({ badges, pullRequestState, pinned }: TodaySessionBadgesProps): JSX.Element {
    return (
        <AvatarGroup stacked reverse size="xs" className="shrink-0">
            {pinned && (
                <IconBadge label="Pinned">
                    <IconPinFilled className="size-2.5 text-primary" />
                </IconBadge>
            )}
            {badges.map((badge) => {
                switch (badge.kind) {
                    case 'source':
                        return (
                            <IconBadge key={badge.kind} label={`Source: ${recentSourceLabel(badge.source)}`}>
                                {badge.source === 'slack' ? (
                                    <IconSlack className="size-2.5" />
                                ) : (
                                    <IconArrowRightDown className="size-2.5 text-muted-foreground" />
                                )}
                            </IconBadge>
                        )
                    case 'pullRequest':
                        return (
                            <PullRequestBadge
                                key={badge.kind}
                                pullRequest={badge.pullRequest}
                                pullRequestState={pullRequestState}
                            />
                        )
                    case 'local':
                        return (
                            <IconBadge key={badge.kind} label="Local">
                                <IconLaptop className="size-2.5 text-muted-foreground" />
                            </IconBadge>
                        )
                }
            })}
        </AvatarGroup>
    )
}

function IconBadge({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={200}
                render={<Avatar size="xs" role="img" aria-label={label} className={BADGE_CLASS} />}
            >
                <AvatarFallback className="bg-transparent">{children}</AvatarFallback>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}

function PullRequestBadge({
    pullRequest,
    pullRequestState,
}: {
    pullRequest: TaskPullRequest
    pullRequestState: PrStateEnumApi | null | undefined
}): JSX.Element {
    const known = pullRequestStateMeta(pullRequestState)
    return (
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
                    <IconPullRequest className={cn('size-2.5', known?.iconClassName ?? 'text-muted-foreground')} />
                </AvatarFallback>
            </TooltipTrigger>
            <TooltipContent>
                {`${known?.label ?? 'Pull request'} · ${pullRequest.repository}#${pullRequest.number}`}
            </TooltipContent>
        </Tooltip>
    )
}
