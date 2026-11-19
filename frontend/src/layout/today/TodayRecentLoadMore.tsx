import { useEffect, useRef, useState } from 'react'

import { Button, Spinner, Text } from '@posthog/quill'

const PREFETCH_DISTANCE_PX = 240

function scrollParent(node: HTMLElement): HTMLElement | null {
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const { overflowY } = getComputedStyle(parent)
        if (overflowY === 'auto' || overflowY === 'scroll') {
            return parent
        }
    }
    return null
}

export interface TodayRecentLoadMoreProps {
    hasMore: boolean
    loading: boolean
    failed: boolean
    shownCount: number
    onLoadMore: () => void
}

export function TodayRecentLoadMore({
    hasMore,
    loading,
    failed,
    shownCount,
    onLoadMore,
}: TodayRecentLoadMoreProps): JSX.Element | null {
    const ref = useRef<HTMLDivElement>(null)
    const shownAtLoad = useRef<number | null>(null)
    const [auto, setAuto] = useState(true)

    useEffect(() => setAuto(true), [shownCount])

    useEffect(() => {
        if (loading) {
            shownAtLoad.current = shownCount
            return
        }
        if (shownAtLoad.current === shownCount) {
            setAuto(false)
        }
        shownAtLoad.current = null
    }, [loading, shownCount])

    useEffect(() => {
        const node = ref.current
        if (!node || !hasMore || !auto || loading || failed) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    onLoadMore()
                }
            },
            { root: scrollParent(node), rootMargin: `0px 0px ${PREFETCH_DISTANCE_PX}px 0px` }
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [hasMore, auto, loading, failed, onLoadMore])

    if (!hasMore) {
        return null
    }

    return (
        <div ref={ref} data-attr="today-recent-load-more">
            {failed ? (
                <div className="flex flex-col items-start gap-2 px-2 py-1">
                    <Text size="xs" variant="muted">
                        Older chats didn’t load.
                    </Text>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onLoadMore()}
                        data-attr="today-recent-load-more-retry"
                    >
                        Try again
                    </Button>
                </div>
            ) : loading ? (
                <div role="status" aria-label="Loading older chats" className="flex h-7 items-center px-2">
                    <Spinner />
                </div>
            ) : auto ? (
                <div aria-hidden className="h-px" />
            ) : (
                <div className="px-2 py-1">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onLoadMore()}
                        data-attr="today-recent-load-more-button"
                    >
                        Load older chats
                    </Button>
                </div>
            )}
        </div>
    )
}
