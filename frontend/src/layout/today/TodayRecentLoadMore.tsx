import { useEffect, useRef } from 'react'

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
    loading: boolean
    failed: boolean
    onLoadMore: () => void
}

export function TodayRecentLoadMore({ loading, failed, onLoadMore }: TodayRecentLoadMoreProps): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const node = ref.current
        if (!node || loading || failed) {
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
    }, [loading, failed, onLoadMore])

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
            ) : (
                <div aria-hidden className="h-px" />
            )}
        </div>
    )
}
