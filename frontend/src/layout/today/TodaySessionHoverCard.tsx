import { IconPinFilled, IconPullRequest } from '@posthog/icons'
import { Item, ItemContent, ItemSeparator, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'
import { TaskUserAvatar, taskUserName } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { TodaySessionPreview } from './todayPreviewCards'
import { TodaySessionStatusDot } from './TodaySessionStatusDot'

function Fact({ label, children }: { label: string; children: JSX.Element | string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 text-xs">
            <Text size="xs" variant="muted" render={<span />} className="w-16 shrink-0">
                {label}
            </Text>
            <span className="min-w-0 flex-1 truncate">{children}</span>
        </div>
    )
}

/** A session row's hover card: what the row's marks mean in words, where the work sits, and what the agent said last. */
export function TodaySessionHoverCard({ preview }: { preview: TodaySessionPreview }): JSX.Element {
    const { dot, pullRequest, author } = preview
    const pullRequestState = pullRequestStateMeta(preview.pullRequestState)
    return (
        <div className="flex flex-col" data-attr="today-session-hover-card">
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-2">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long URL in it would widen the card. */}
                    <ItemTitle className="flex items-start gap-2 wrap-anywhere">
                        <span className="flex h-lh w-4 shrink-0 items-center justify-center">
                            <TodaySessionStatusDot dot={dot} />
                        </span>
                        <span className="min-w-0 font-semibold">{preview.title}</span>
                    </ItemTitle>
                    <div className="flex flex-col gap-1 pl-6">
                        {preview.repository && <Fact label="Repo">{preview.repository}</Fact>}
                        {preview.spaceName && <Fact label="Space">{preview.spaceName}</Fact>}
                        {author && (
                            <Fact label="Created by">
                                <span className="flex min-w-0 items-center gap-1.5">
                                    <TaskUserAvatar user={author} />
                                    <span className="truncate">{taskUserName(author)}</span>
                                </span>
                            </Fact>
                        )}
                        {preview.timestamp && <Fact label="Updated">{dayjs(preview.timestamp).fromNow()}</Fact>}
                    </div>
                </ItemContent>
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
        </div>
    )
}
