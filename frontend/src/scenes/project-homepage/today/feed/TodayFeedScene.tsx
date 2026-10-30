import '../Today.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheckCircle, IconNewspaper } from '@posthog/icons'
import {
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Heading,
    Skeleton,
    SkeletonText,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { todayFeedLogic } from './todayFeedLogic'
import { TodayFeedPost } from './TodayFeedPost'

export const scene: SceneExport = {
    component: TodayFeedScene,
    logic: todayFeedLogic,
}

function TodayFeedSkeleton(): JSX.Element {
    return (
        <div aria-busy aria-label="Loading the feed">
            {[0, 1, 2].map((index) => (
                <div key={index} className="flex gap-3 border-b border-border px-4 py-3">
                    <Skeleton className="size-10 shrink-0 rounded-full" />
                    <div className="flex flex-1 flex-col gap-2">
                        <Skeleton className="h-4 w-1/3" />
                        <SkeletonText lines={2} />
                        <Skeleton className="h-28 w-full rounded-lg" />
                    </div>
                </div>
            ))}
        </div>
    )
}

function TodayFeedEnd({ postCount }: { postCount: number }): JSX.Element {
    const { endReached } = useActions(todayFeedLogic)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                endReached(postCount)
                observer.disconnect()
            }
        })
        observer.observe(element)
        return () => observer.disconnect()
    }, [endReached, postCount])

    return (
        <div ref={ref} className="flex flex-col items-center gap-1 px-4 py-10 text-center">
            <IconCheckCircle className="size-6 text-muted-foreground" aria-hidden />
            <Text size="sm" weight="semibold">
                You're all caught up
            </Text>
            <Text size="xs" variant="muted">
                New posts show up here as your data changes.
            </Text>
        </div>
    )
}

function TodayFeedContent(): JSX.Element {
    const { feedPosts, feedReady } = useValues(todayFeedLogic)

    return (
        <div className="Today flex min-h-full flex-1 justify-center" data-quill>
            <main className="flex min-h-full w-full max-w-xl flex-col border-x border-border">
                <header className="sticky top-0 z-10 flex flex-col gap-0.5 border-b border-border bg-background px-4 py-3">
                    <Heading size="lg" render={<h1 />} className="m-0">
                        Feed
                    </Heading>
                    <Text size="xs" variant="muted">
                        Changes in your data, sessions worth watching and new things to try.
                    </Text>
                </header>
                {!feedReady ? (
                    <TodayFeedSkeleton />
                ) : feedPosts.length === 0 ? (
                    <Empty className="py-16">
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <IconNewspaper />
                            </EmptyMedia>
                            <EmptyTitle>Nothing to show yet</EmptyTitle>
                            <EmptyDescription>
                                Posts show up here when your events change, when a session is worth watching, or when
                                your team saves something new.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <>
                        {feedPosts.map((post, position) => (
                            <TodayFeedPost key={post.key} post={post} position={position} />
                        ))}
                        <TodayFeedEnd postCount={feedPosts.length} />
                    </>
                )}
            </main>
        </div>
    )
}

export function TodayFeedScene(): JSX.Element {
    const railEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const feedEnabled = useFeatureFlag('TODAY_FEED')
    // The page ships behind the Today navigation and its own flag, so without them `/feed` stays a missing page.
    return railEnabled && feedEnabled ? <TodayFeedContent /> : <NotFound object="page" />
}
