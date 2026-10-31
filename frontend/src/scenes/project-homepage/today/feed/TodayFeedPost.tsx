import { useActions, useValues } from 'kea'

import { IconArrowUpRight, IconHeart, IconHeartFilled, IconHide } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayFeedAvatar } from './TodayFeedAvatar'
import type { TodayFeedPost as TodayFeedPostType } from './todayFeedItems'
import { todayFeedLogic } from './todayFeedLogic'
import { TodayFeedPostMedia } from './TodayFeedPostMedia'

export function TodayFeedPost({ post, position }: { post: TodayFeedPostType; position: number }): JSX.Element {
    const { likedKeys } = useValues(todayFeedLogic)
    const { postOpened, postHidden, postLiked } = useActions(todayFeedLogic)
    const liked = !!likedKeys[post.key]
    const open = (): void => postOpened(post, position)

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
                <TodayFeedPostMedia post={post} position={position} />
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
