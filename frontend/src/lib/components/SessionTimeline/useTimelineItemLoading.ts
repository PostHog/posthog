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
            await Promise.all([collector.loadBefore(batch), collector.loadAfter(batch)])
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

                const scrollTop = el.scrollTop
                const scrollHeight = el.scrollHeight
                const loadPromises: Promise<void>[] = []
                if (collector.hasMoreBefore) {
                    loadPromises.push(collector.loadBefore(batch))
                }
                if (collector.hasMoreAfter) {
                    loadPromises.push(collector.loadAfter(batch))
                }

                await Promise.all(loadPromises)
                if (cancelled) {
                    return
                }

                setItems(collector.collectItems())
                await nextFrame()
                if (cancelled) {
                    return
                }

                if (collector.hasMoreBefore) {
                    el.scrollTop = scrollTop + (el.scrollHeight - scrollHeight)
                }
            }
        }

        void loadInitialItems().finally(() => {
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
            let previousItemCount = collector.collectItems().length

            while (
                !cancelled &&
                el.scrollHeight <= el.clientHeight &&
                refillIterations < MAX_FILTER_REFILL_ITERATIONS
            ) {
                refillIterations++

                if (!collector.hasMoreBefore && !collector.hasMoreAfter) {
                    break
                }

                const scrollTop = el.scrollTop
                const scrollHeight = el.scrollHeight
                const batch = calculateBatchSize(el)
                const loadedBefore = collector.hasMoreBefore

                const loadPromises: Promise<void>[] = []
                if (collector.hasMoreBefore) {
                    loadPromises.push(collector.loadBefore(batch))
                }
                if (collector.hasMoreAfter) {
                    loadPromises.push(collector.loadAfter(batch))
                }

                if (loadPromises.length === 0) {
                    break
                }

                await Promise.all(loadPromises)
                if (cancelled) {
                    return
                }

                const nextItems = collector.collectItems()
                setItems(nextItems)

                // Safety valve: avoid spinning if a loader reports "has more"
                // but does not append anything.
                if (nextItems.length <= previousItemCount) {
                    break
                }
                previousItemCount = nextItems.length

                await nextFrame()
                if (cancelled) {
                    return
                }

                if (loadedBefore) {
                    el.scrollTop = scrollTop + (el.scrollHeight - scrollHeight)
                }
            }
        }

        void refillAfterFilter().finally(() => {
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

        scrollLoadingRef.current = 'before'
        setScrollLoading('before')

        try {
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
        } finally {
            scrollLoadingRef.current = null
            setScrollLoading(null)
        }
    }, [collector, containerRef, loading])

    const handleScrollBottom = useCallback(async (): Promise<void> => {
        if (loading || !collector.hasMoreAfter || scrollLoadingRef.current) {
            return
        }

        scrollLoadingRef.current = 'after'
        setScrollLoading('after')

        try {
            const batch = calculateBatchSize(containerRef.current)
            await collector.loadAfter(batch)
            setItems(collector.collectItems())
        } finally {
            scrollLoadingRef.current = null
            setScrollLoading(null)
        }
    }, [collector, containerRef, loading])

    return {
        items,
        loading,
        scrollLoading,
        handleScrollTop,
        handleScrollBottom,
    }
}
