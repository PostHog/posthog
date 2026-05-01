import { RefObject, useCallback, useEffect, useRef, useState } from 'react'

import { ItemCategory, ItemCollector, TimelineItem } from './timeline'

const ITEM_HEIGHT_PX = 32 // matches h-[2rem]
const BUFFER_FACTOR = 1.5
const MAX_FILL_ITERATIONS = 10
const MAX_FILTER_REFILL_ITERATIONS = 30

/** Promise that resolves after the next animation frame. */
const nextFrame = (): Promise<void> => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

function calculateBatchSize(containerEl: HTMLElement | null): number {
    if (!containerEl) {
        return 25
    }
    return Math.max(10, Math.ceil((containerEl.clientHeight / ITEM_HEIGHT_PX) * BUFFER_FACTOR))
}

function countVisibleItems(items: TimelineItem[], activeCategorySet: Set<ItemCategory>): number {
    return items.filter((item) => activeCategorySet.has(item.category)).length
}

function ignoreLoadingError(): void {
    // Keep timeline interactions resilient when one background load fails.
}

async function loadAvailableDirections(
    collector: ItemCollector,
    batch: number
): Promise<{ loadedBefore: boolean; loadedAfter: boolean }> {
    const loadedBefore = collector.hasMoreBefore
    const loadedAfter = collector.hasMoreAfter

    const loadPromises: Promise<void>[] = []
    if (loadedBefore) {
        loadPromises.push(collector.loadBefore(batch))
    }
    if (loadedAfter) {
        loadPromises.push(collector.loadAfter(batch))
    }

    if (loadPromises.length > 0) {
        await Promise.all(loadPromises)
    }

    return { loadedBefore, loadedAfter }
}

async function loadAndSyncViewport({
    collector,
    el,
    batch,
    applyItems,
}: {
    collector: ItemCollector
    el: HTMLDivElement
    batch: number
    applyItems: (items: TimelineItem[]) => void
}): Promise<{ loadedBefore: boolean; loadedAfter: boolean; nextItems: TimelineItem[] }> {
    const scrollTop = el.scrollTop
    const scrollHeight = el.scrollHeight
    const { loadedBefore, loadedAfter } = await loadAvailableDirections(collector, batch)
    const nextItems = collector.collectItems()

    if (!loadedBefore && !loadedAfter) {
        return { loadedBefore, loadedAfter, nextItems }
    }

    applyItems(nextItems)
    await nextFrame()

    if (loadedBefore) {
        el.scrollTop = scrollTop + (el.scrollHeight - scrollHeight)
    }

    return { loadedBefore, loadedAfter, nextItems }
}

export interface UseTimelineItemLoadingProps {
    collector: ItemCollector
    selectedItemId?: string
    activeCategorySet: Set<ItemCategory>
    containerRef: RefObject<HTMLDivElement | null>
    scrollToItem: (itemId: string) => void
}

export interface UseTimelineItemLoadingResult {
    items: TimelineItem[]
    loading: boolean
    scrollLoading: 'before' | 'after' | null
    handleScrollTop: () => Promise<void>
    handleScrollBottom: () => Promise<void>
}

export function useTimelineItemLoading({
    collector,
    selectedItemId,
    activeCategorySet,
    containerRef,
    scrollToItem,
}: UseTimelineItemLoadingProps): UseTimelineItemLoadingResult {
    const [items, setItems] = useState<TimelineItem[]>([])
    const [loading, setLoading] = useState(false)
    const [scrollLoading, setScrollLoading] = useState<'before' | 'after' | null>(null)

    const scrollLoadingRef = useRef<'before' | 'after' | null>(null)
    const filterRefillInProgressRef = useRef(false)
    const selectedItemIdRef = useRef(selectedItemId)

    useEffect(() => {
        selectedItemIdRef.current = selectedItemId
    }, [selectedItemId])

    const runWithScrollLoading = useCallback(
        async (direction: 'before' | 'after', operation: () => Promise<void>): Promise<void> => {
            scrollLoadingRef.current = direction
            setScrollLoading(direction)

            try {
                await operation()
            } finally {
                scrollLoadingRef.current = null
                setScrollLoading(null)
            }
        },
        []
    )

    // Initial load + auto-fill
    useEffect(() => {
        let cancelled = false

        const loadInitialItems = async (): Promise<void> => {
            collector.clear()
            scrollLoadingRef.current = null
            setScrollLoading(null)
            setItems([])
            setLoading(true)

            const batch = calculateBatchSize(containerRef.current)
            await loadAvailableDirections(collector, batch)
            if (cancelled) {
                return
            }

            setItems(collector.collectItems())

            if (selectedItemIdRef.current) {
                await nextFrame()
                if (!cancelled && selectedItemIdRef.current) {
                    scrollToItem(selectedItemIdRef.current)
                }
            }

            const el = containerRef.current
            if (!el) {
                return
            }

            await nextFrame()
            if (cancelled) {
                return
            }

            let fillIterations = 0
            while (el.scrollHeight <= el.clientHeight && fillIterations < MAX_FILL_ITERATIONS) {
                fillIterations++
                if (!collector.hasMoreBefore && !collector.hasMoreAfter) {
                    break
                }

                const { loadedBefore, loadedAfter } = await loadAndSyncViewport({
                    collector,
                    el,
                    batch,
                    applyItems: setItems,
                })
                if (!loadedBefore && !loadedAfter) {
                    break
                }
                if (cancelled) {
                    return
                }
            }
        }

        void loadInitialItems()
            .catch(ignoreLoadingError)
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })

        return () => {
            cancelled = true
        }
    }, [collector, containerRef, scrollToItem])

    useEffect(() => {
        if (!selectedItemId) {
            return
        }

        scrollToItem(selectedItemId)
    }, [selectedItemId, scrollToItem])

    // If category filtering shrinks the visible list below container height,
    // proactively load more items so users can keep browsing without needing
    // an impossible scroll event.
    useEffect(() => {
        if (loading || scrollLoading !== null || filterRefillInProgressRef.current) {
            return
        }

        const el = containerRef.current
        if (!el || el.scrollHeight > el.clientHeight) {
            return
        }

        if (!collector.hasMoreBefore && !collector.hasMoreAfter) {
            return
        }

        let cancelled = false
        filterRefillInProgressRef.current = true

        const refillAfterFilter = async (): Promise<void> => {
            let refillIterations = 0
            let previousFilteredItemCount = countVisibleItems(collector.collectItems(), activeCategorySet)

            while (
                !cancelled &&
                el.scrollHeight <= el.clientHeight &&
                refillIterations < MAX_FILTER_REFILL_ITERATIONS
            ) {
                refillIterations++

                if (!collector.hasMoreBefore && !collector.hasMoreAfter) {
                    break
                }

                const batch = calculateBatchSize(el)
                const { loadedBefore, loadedAfter, nextItems } = await loadAndSyncViewport({
                    collector,
                    el,
                    batch,
                    applyItems: setItems,
                })
                if (!loadedBefore && !loadedAfter) {
                    break
                }
                if (cancelled) {
                    return
                }

                const nextFilteredItemCount = countVisibleItems(nextItems, activeCategorySet)

                // Safety valve: avoid spinning when no new visible items are produced.
                if (nextFilteredItemCount <= previousFilteredItemCount) {
                    break
                }
                previousFilteredItemCount = nextFilteredItemCount
            }
        }

        void refillAfterFilter()
            .catch(ignoreLoadingError)
            .finally(() => {
                if (!cancelled) {
                    filterRefillInProgressRef.current = false
                }
            })

        return () => {
            cancelled = true
            filterRefillInProgressRef.current = false
        }
    }, [activeCategorySet, collector, containerRef, loading, scrollLoading])

    const handleScrollTop = useCallback(async (): Promise<void> => {
        if (loading || !collector.hasMoreBefore || scrollLoadingRef.current) {
            return
        }

        await runWithScrollLoading('before', async () => {
            const el = containerRef.current
            const scrollTop = el?.scrollTop || 0
            const scrollHeight = el?.scrollHeight || 0
            const batch = calculateBatchSize(el)

            await collector.loadBefore(batch)
            setItems(collector.collectItems())

            requestAnimationFrame(() => {
                const newScrollHeight = el?.scrollHeight || 0
                if (el) {
                    el.scrollTop = scrollTop + (newScrollHeight - scrollHeight)
                }
            })
        })
    }, [collector, containerRef, loading, runWithScrollLoading])

    const handleScrollBottom = useCallback(async (): Promise<void> => {
        if (loading || !collector.hasMoreAfter || scrollLoadingRef.current) {
            return
        }

        await runWithScrollLoading('after', async () => {
            const batch = calculateBatchSize(containerRef.current)
            await collector.loadAfter(batch)
            setItems(collector.collectItems())
        })
    }, [collector, containerRef, loading, runWithScrollLoading])

    return {
        items,
        loading,
        scrollLoading,
        handleScrollTop,
        handleScrollBottom,
    }
}
