import { ReactNode, useCallback, useRef } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const INTERACTIVE_DELAY = 500
const HIDE_DELAY = 100

let hoverElement: HTMLElement | null = null
let hoverRoot: Root | null = null
let hoverOwner: string | null = null
let hoverIsMouseOver = false
let hoverHideTimeout: ReturnType<typeof setTimeout> | null = null
let hoverInteractiveTimeout: ReturnType<typeof setTimeout> | null = null
let lastRenderedHoverElement: ReactNode = null

let pinnedElement: HTMLElement | null = null
let pinnedRoot: Root | null = null
let pinnedOwner: string | null = null
let pinnedOnUnpin: (() => void) | null = null

let activeRenderId: string | null = null

const wrappedHoverRoot: Root = {
    render: (children: ReactNode): void => {
        if (activeRenderId === null || hoverOwner !== activeRenderId) {
            return
        }
        lastRenderedHoverElement = children
        hoverRoot?.render(children)
    },
    unmount: (): void => {
        hoverRoot?.unmount()
    },
}

function clearHoverHideTimeout(): void {
    if (hoverHideTimeout) {
        clearTimeout(hoverHideTimeout)
        hoverHideTimeout = null
    }
}

function clearHoverInteractiveTimeout(): void {
    if (hoverInteractiveTimeout) {
        clearTimeout(hoverInteractiveTimeout)
        hoverInteractiveTimeout = null
    }
}

function disableHoverInteractivity(): void {
    if (hoverElement) {
        hoverElement.style.pointerEvents = 'none'
    }
    clearHoverInteractiveTimeout()
}

function scheduleHoverInteractivity(): void {
    clearHoverInteractiveTimeout()
    hoverInteractiveTimeout = setTimeout(() => {
        if (hoverElement) {
            hoverElement.style.pointerEvents = 'auto'
        }
        hoverInteractiveTimeout = null
    }, INTERACTIVE_DELAY)
}

function hideHoverNow(): void {
    if (hoverElement) {
        hoverElement.style.opacity = '0'
    }
    disableHoverInteractivity()
}

function onHoverMouseEnter(): void {
    hoverIsMouseOver = true
    clearHoverHideTimeout()
}

function onHoverMouseLeave(): void {
    hoverIsMouseOver = false
    disableHoverInteractivity()
    clearHoverHideTimeout()
    hoverHideTimeout = setTimeout(() => {
        if (!hoverIsMouseOver) {
            hideHoverNow()
        }
    }, HIDE_DELAY)
}

function ensureHoverDom(): void {
    if (hoverElement) {
        return
    }
    const el = document.createElement('div')
    el.id = 'InsightTooltipWrapper-hover'
    el.classList.add('InsightTooltipWrapper', 'ph-no-capture')
    el.setAttribute('data-attr', 'insight-tooltip-wrapper')
    el.style.pointerEvents = 'none'
    el.style.opacity = '0'
    el.style.position = 'absolute'
    document.body.appendChild(el)
    el.addEventListener('mouseenter', onHoverMouseEnter, { passive: true })
    el.addEventListener('mouseleave', onHoverMouseLeave, { passive: true })
    hoverElement = el
    hoverRoot = createRoot(el)
}

function ensurePinnedDom(): void {
    if (pinnedElement) {
        return
    }
    const el = document.createElement('div')
    el.id = 'InsightTooltipWrapper-pinned'
    el.classList.add('InsightTooltipWrapper', 'InsightTooltipWrapper--pinned', 'ph-no-capture')
    el.setAttribute('data-attr', 'insight-tooltip-wrapper-pinned')
    el.style.pointerEvents = 'auto'
    el.style.opacity = '0'
    el.style.position = 'absolute'
    document.body.appendChild(el)
    pinnedElement = el
    pinnedRoot = createRoot(el)
}

let globalScrollEndListenerActive = false

function initGlobalScrollEndListener(onScrollEnd: (id: string) => void): void {
    if (globalScrollEndListenerActive) {
        return
    }
    globalScrollEndListenerActive = true
    document.addEventListener(
        'scrollend',
        (e) => {
            if (!pinnedOwner || !pinnedElement) {
                return
            }
            if (e.target instanceof Node && pinnedElement.contains(e.target as Node)) {
                return
            }
            onScrollEnd(pinnedOwner)
        },
        { capture: true, passive: true }
    )
}

let globalUnpinListenersActive = false

function initGlobalUnpinListeners(): void {
    if (globalUnpinListenersActive) {
        return
    }
    globalUnpinListenersActive = true
    document.addEventListener(
        'click',
        (e) => {
            if (!pinnedOwner || !pinnedElement) {
                return
            }
            if (e.target instanceof Node && pinnedElement.contains(e.target as Node)) {
                return
            }
            unpinTooltip(pinnedOwner)
        },
        { passive: true }
    )

    document.addEventListener(
        'keydown',
        (e) => {
            if (e.key === 'Escape' && pinnedOwner) {
                unpinTooltip(pinnedOwner)
            }
        },
        { passive: true }
    )
}

export function ensureTooltip(id: string): [Root, HTMLElement] {
    ensureHoverDom()
    if (pinnedOwner === id) {
        hideHoverNow()
        activeRenderId = null
        return [wrappedHoverRoot, hoverElement!]
    }
    hoverOwner = id
    activeRenderId = id
    return [wrappedHoverRoot, hoverElement!]
}

export function showTooltip(id: string): void {
    if (activeRenderId !== id || !hoverElement) {
        return
    }
    clearHoverHideTimeout()
    hoverElement.style.opacity = '1'
}

export function hideTooltip(id?: string): void {
    if (id && activeRenderId !== id) {
        return
    }
    if (!hoverElement) {
        return
    }
    clearHoverHideTimeout()
    if (hoverIsMouseOver) {
        return
    }
    hoverHideTimeout = setTimeout(() => {
        if (!hoverIsMouseOver) {
            hideHoverNow()
        }
    }, HIDE_DELAY)
}

export function pinTooltip(id: string, onUnpin?: () => void): void {
    if (!hoverElement) {
        return
    }
    ensurePinnedDom()
    if (pinnedOwner && pinnedOwner !== id) {
        const previousOnUnpin = pinnedOnUnpin
        pinnedOnUnpin = null
        previousOnUnpin?.()
    }
    pinnedRoot?.render(lastRenderedHoverElement)
    if (pinnedElement) {
        pinnedElement.style.left = hoverElement.style.left
        pinnedElement.style.top = hoverElement.style.top
        pinnedElement.style.opacity = '1'
        pinnedElement.style.pointerEvents = 'auto'
    }
    pinnedOwner = id
    pinnedOnUnpin = onUnpin ?? null

    hideHoverNow()
    if (hoverOwner === id) {
        hoverOwner = null
    }
    activeRenderId = null
}

export function unpinTooltip(id: string): void {
    if (pinnedOwner !== id) {
        return
    }
    const callback = pinnedOnUnpin
    pinnedOnUnpin = null
    pinnedOwner = null
    pinnedRoot?.render(null)
    if (pinnedElement) {
        pinnedElement.style.opacity = '0'
        pinnedElement.style.pointerEvents = 'none'
    }
    callback?.()
}

export function cleanupTooltip(id: string): void {
    if (hoverOwner !== id && pinnedOwner !== id) {
        return
    }
    if (hoverOwner === id) {
        hoverOwner = null
        if (activeRenderId === id) {
            activeRenderId = null
        }
        lastRenderedHoverElement = null
        hoverRoot?.render(null)
        hideHoverNow()
    }
    if (pinnedOwner === id) {
        const callback = pinnedOnUnpin
        pinnedOnUnpin = null
        pinnedOwner = null
        pinnedRoot?.render(null)
        if (pinnedElement) {
            pinnedElement.style.opacity = '0'
            pinnedElement.style.pointerEvents = 'none'
        }
        callback?.()
    }
}

function applyPosition(
    tooltipEl: HTMLElement,
    canvasBounds: DOMRect,
    caretX: number,
    caretY: number,
    centerVertically: boolean
): void {
    const caretLeft = canvasBounds.left + window.scrollX + caretX
    let left = caretLeft + 8
    const verticalOffset = centerVertically ? -tooltipEl.clientHeight / 2 : 8
    const top = canvasBounds.top + window.scrollY + caretY + verticalOffset

    const viewportRight = window.scrollX + document.documentElement.clientWidth
    const tooltipWidth = tooltipEl.offsetWidth
    if (tooltipWidth > 0 && left + tooltipWidth > viewportRight - 8) {
        left = caretLeft - tooltipWidth - 8
    }
    left = Math.max(window.scrollX + 8, left)

    const viewportBottom = window.scrollY + document.documentElement.clientHeight
    const clampedTop = Math.min(
        Math.max(window.scrollY + 8, top),
        viewportBottom - Math.max(tooltipEl.offsetHeight, 0) - 8
    )

    tooltipEl.style.left = `${left}px`
    tooltipEl.style.top = `${clampedTop}px`
}

export function positionTooltip(
    tooltipEl: HTMLElement,
    canvasBounds: DOMRect,
    caretX: number,
    caretY: number,
    centerVertically = false
): void {
    if (tooltipEl !== hoverElement) {
        return
    }
    if (activeRenderId === null) {
        return
    }
    const id = activeRenderId
    tooltipEl.style.position = 'absolute'
    tooltipEl.style.maxWidth = ''
    disableHoverInteractivity()
    scheduleHoverInteractivity()
    applyPosition(tooltipEl, canvasBounds, caretX, caretY, centerVertically)
    if (tooltipEl.offsetWidth === 0) {
        requestAnimationFrame(() => {
            if (activeRenderId !== id) {
                return
            }
            applyPosition(tooltipEl, canvasBounds, caretX, caretY, centerVertically)
        })
    }
}

export function useInsightTooltip(options?: { isPinnable?: boolean }): {
    tooltipId: string
    getTooltip: () => [Root, HTMLElement]
    showTooltip: () => void
    hideTooltip: () => void
    cleanupTooltip: () => void
    positionTooltip: typeof positionTooltip
    pinTooltip: ((onUnpin?: () => void) => void) | null
} {
    const isPinnable = options?.isPinnable ?? false
    const tooltipIdRef = useRef<string | null>(null)
    if (tooltipIdRef.current === null) {
        tooltipIdRef.current = Math.random().toString(36).substring(2, 11)
    }
    const tooltipId = tooltipIdRef.current

    useOnMountEffect(() => {
        if (isPinnable) {
            initGlobalScrollEndListener((id) => unpinTooltip(id))
            initGlobalUnpinListeners()
        } else {
            initGlobalScrollEndListener((id) => unpinTooltip(id))
        }

        return () => {
            cleanupTooltip(tooltipId)
        }
    })

    const getTooltip = useCallback((): [Root, HTMLElement] => ensureTooltip(tooltipId), [tooltipId])
    const show = useCallback((): void => showTooltip(tooltipId), [tooltipId])
    const hide = useCallback((): void => hideTooltip(tooltipId), [tooltipId])
    const cleanup = useCallback((): void => cleanupTooltip(tooltipId), [tooltipId])
    const pin = useCallback((onUnpin?: () => void): void => pinTooltip(tooltipId, onUnpin), [tooltipId])

    return {
        tooltipId,
        getTooltip,
        showTooltip: show,
        hideTooltip: hide,
        cleanupTooltip: cleanup,
        positionTooltip,
        pinTooltip: isPinnable ? pin : null,
    }
}
