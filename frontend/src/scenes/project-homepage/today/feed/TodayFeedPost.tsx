import { useActions, useValues } from 'kea'

import { IconArrowUpRight, IconHeart, IconHeartFilled, IconHide } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReportChartCard } from 'products/signals/frontend/inbox/components/detail/ReportChart'

import { TodayFeedAvatar } from './TodayFeedAvatar'
import { TodayFeedCard } from './TodayFeedCard'
import { TodayFeedChart } from './TodayFeedChart'
import type { TodayFeedPost as TodayFeedPostType } from './todayFeedItems'
import { todayFeedLogic } from './todayFeedLogic'
import { TodayFeedReplay } from './TodayFeedReplay'

export function TodayFeedPost({ post, position }: { post: TodayFeedPostType; position: number }): JSX.Element {
    const { likedKeys, enrolledFlagKeys } = useValues(todayFeedLogic)
    const { postOpened, postHidden, postLiked, postEnrolled, postPlayed } = useActions(todayFeedLogic)
    const liked = !!likedKeys[post.key]
    const open = (): void => postOpened(post, position)
    const { media } = post

    return (
        <article className="flex gap-3 border-b border-border px-4 py-3" aria-label={post.author.name}>
            <TodayFeedAvatar author={post.author} />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="flex min-w-0 items-baseline gap-1">
                        <Text size="sm" weight="semibold" className="truncate">
                            {post.author.name}
                        </Text>
                        <Text size="sm" variant="muted" className="truncate">
                            {post.author.handle}
                        </Text>
                        {post.at && (
                            <>
                                <Text size="sm" variant="muted" aria-hidden>
                                    ·
                                </Text>
                                <Text size="sm" variant="muted" className="shrink-0">
                                    <TZLabel time={post.at} noStyles />
                                </Text>
                            </>
                        )}
                    </span>
                    {post.text && (
                        <Text size="sm" render={<p />} className="m-0 text-pretty">
                            {post.text}
                        </Text>
                    )}
                </div>
                {media?.type === 'chart' ? (
                    <TodayFeedChart
                        label={media.label}
                        current={media.current}
                        previous={media.previous}
                        series={media.series}
                        days={media.days}
                        to={post.to}
                        onOpen={open}
                    />
                ) : media?.type === 'report-chart' ? (
                    <ReportChartCard chart={media.chart} />
                ) : media?.type === 'replay' ? (
                    <TodayFeedReplay
                        sessionId={media.sessionId}
                        page={media.page}
                        caption={media.caption}
                        to={post.to}
                        onPlay={() => postPlayed(post, position)}
                        onOpen={open}
                    />
                ) : media?.type === 'card' ? (
                    <TodayFeedCard
                        title={media.title}
                        description={media.description}
                        actionLabel={media.actionLabel}
                        to={post.to}
                        onOpen={open}
                        onEnroll={media.enrollFlagKey ? () => postEnrolled(post, position) : undefined}
                        enrolled={!!media.enrollFlagKey && !!enrolledFlagKeys[media.enrollFlagKey]}
                    />
                ) : null}
                <div className="-ml-2 flex items-center gap-4">
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label={liked ? 'Unlike' : 'Like'}
                        aria-pressed={liked}
                        tooltip={liked ? 'Unlike' : 'Like'}
                        onClick={() => postLiked(post, position, !liked)}
                        data-attr="today-feed-like"
                    >
                        {liked ? <IconHeartFilled className="text-destructive-foreground" /> : <IconHeart />}
                    </Button>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Not interested"
                        tooltip="Not interested"
                        onClick={() => postHidden(post, position)}
                        data-attr="today-feed-hide"
                    >
                        <IconHide />
                    </Button>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Open"
                        tooltip="Open"
                        render={<LinkPrimitive to={post.to} onClick={open} />}
                        data-attr="today-feed-open"
                    >
                        <IconArrowUpRight />
                    </Button>
                </div>
            </div>
        </article>
    )
}
