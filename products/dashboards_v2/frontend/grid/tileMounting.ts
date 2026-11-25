import { type RefObject, createContext, useContext, useEffect, useState } from 'react'

import { scrollParentOf } from './scrollParent'

/** How far past the scrolled view a tile still counts as in range, so a scroll finds it already drawn. */
const OVERSCAN_PX = 800
/** Scrolling counts as stopped once no scroll event has come for this long. */
const SETTLE_MS = 150
/** Tiles mounted per frame while the page scrolls: enough to keep up, few enough to keep the scroll smooth. */
const PER_FRAME_WHILE_SCROLLING = 2

/**
 * Decides which tiles have their content mounted. A tile mounts when it is near the scrolled view and unmounts when it
 * leaves. New tiles mount a few at a time, nearest the middle of the view first: every frame while the page scrolls, and
 * when the browser is idle otherwise.
 */
export interface TileMountScheduler {
    /** Calls `onMountedChange` when `element` should mount or unmount its content. Returns the stop function. */
    observe: (element: Element, onMountedChange: (mounted: boolean) => void) => () => void
    dispose: () => void
}

const ALWAYS_MOUNTED: TileMountScheduler = {
    observe: (_element, onMountedChange) => {
        onMountedChange(true)
        return () => {}
    },
    dispose: () => {},
}

export function createTileMountScheduler(): TileMountScheduler {
    if (typeof IntersectionObserver === 'undefined') {
        return ALWAYS_MOUNTED
    }
    const listeners = new Map<Element, (mounted: boolean) => void>()
    const mounted = new Set<Element>()
    const waiting = new Set<Element>()
    let observer: IntersectionObserver | null = null
    let root: Element | null = null
    let scrolling = false
    let settleTimer = 0
    let idle: { cancel: () => void } | null = null

    const centreOfView = (): number => {
        const box = root?.getBoundingClientRect() ?? { top: 0, height: window.innerHeight }
        return box.top + box.height / 2
    }

    const mountNext = (count: number): void => {
        idle = null
        if (waiting.size === 0) {
            return
        }
        const centre = centreOfView()
        const distance = (element: Element): number => {
            const box = element.getBoundingClientRect()
            return Math.abs(box.top + box.height / 2 - centre)
        }
        const nearestFirst = [...waiting].sort((a, b) => distance(a) - distance(b))
        for (const element of nearestFirst.slice(0, count)) {
            waiting.delete(element)
            mounted.add(element)
            listeners.get(element)?.(true)
        }
        schedule()
    }

    const schedule = (): void => {
        if (idle || waiting.size === 0) {
            return
        }
        // While scrolling an idle callback may not come until the scroll ends, so tiles mount on the next frame.
        // Safari has no requestIdleCallback, so it gets one tile per frame.
        if (scrolling) {
            const handle = window.requestAnimationFrame(() => mountNext(PER_FRAME_WHILE_SCROLLING))
            idle = { cancel: () => window.cancelAnimationFrame(handle) }
        } else if (typeof window.requestIdleCallback === 'function') {
            const handle = window.requestIdleCallback((deadline) => mountNext(deadline.timeRemaining() > 12 ? 3 : 1), {
                timeout: 500,
            })
            idle = { cancel: () => window.cancelIdleCallback(handle) }
        } else {
            const handle = window.setTimeout(() => mountNext(1), 16)
            idle = { cancel: () => window.clearTimeout(handle) }
        }
    }

    const onScroll = (): void => {
        if (!scrolling) {
            scrolling = true
            // Swap a pending idle callback for a frame callback.
            idle?.cancel()
            idle = null
            schedule()
        }
        window.clearTimeout(settleTimer)
        settleTimer = window.setTimeout(() => {
            scrolling = false
        }, SETTLE_MS)
    }

    const onIntersect = (entries: IntersectionObserverEntry[]): void => {
        for (const { target, isIntersecting } of entries) {
            if (isIntersecting) {
                if (!mounted.has(target)) {
                    waiting.add(target)
                }
            } else {
                waiting.delete(target)
                if (mounted.delete(target)) {
                    listeners.get(target)?.(false)
                }
            }
        }
        schedule()
    }

    const start = (element: Element): IntersectionObserver => {
        root = scrollParentOf(element)
        ;(root ?? window).addEventListener('scroll', onScroll, { passive: true })
        // With no scrolling ancestor the page itself scrolls, and a null root is the browser window.
        return new IntersectionObserver(onIntersect, { root, rootMargin: `${OVERSCAN_PX}px 0px` })
    }

    return {
        observe(element, onMountedChange) {
            observer ??= start(element)
            listeners.set(element, onMountedChange)
            observer.observe(element)
            return () => {
                observer?.unobserve(element)
                listeners.delete(element)
                waiting.delete(element)
                mounted.delete(element)
            }
        },
        dispose() {
            idle?.cancel()
            idle = null
            window.clearTimeout(settleTimer)
            scrolling = false
            ;(root ?? window).removeEventListener('scroll', onScroll)
            observer?.disconnect()
            observer = null
            root = null
            listeners.clear()
            waiting.clear()
            mounted.clear()
        },
    }
}

/** Left out, every tile mounts its content, so a grid rendered outside a dashboard still draws everything. */
export const TileMountContext = createContext<TileMountScheduler | null>(null)

/** The tile being captured as an image. It and everything inside it mount, whatever the scheduler says. */
export const CapturingTileContext = createContext<string | null>(null)

/** Whether the tile around `ref` should mount its content now. */
export function useTileMounted(ref: RefObject<Element>): boolean {
    const scheduler = useContext(TileMountContext)
    const [mounted, setMounted] = useState(scheduler === null)
    useEffect(() => {
        const element = ref.current
        if (!scheduler || !element) {
            return
        }
        return scheduler.observe(element, setMounted)
    }, [scheduler, ref])
    return scheduler === null || mounted
}
