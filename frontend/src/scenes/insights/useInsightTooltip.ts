import { ReactNode, useCallback, useRef } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const INTERACTIVE_DELAY = 500
const HIDE_DELAY = 100

interface SharedTooltipBase {
    element: HTMLElement | null
    root: Root | null
    owner: string | null
}

interface HoverTooltipState extends SharedTooltipBase {
    isMouseOver: boolean
    hideTimeout: ReturnType<typeof setTimeout> | null
    interactiveTimeout: ReturnType<typeof setTimeout> | null
    lastRendered: ReactNode
    lastRenderedOwner: string | null
}

interface PinnedTooltipState extends SharedTooltipBase {
    onUnpin: (() => void) | null
}

const hover: HoverTooltipState = {
    element: null,
    root: null,
    owner: null,
    isMouseOver: false,
    hideTimeout: null,
    interactiveTimeout: null,
    lastRendered: null,
    lastRenderedOwner: null,
}

const pinned: PinnedTooltipState = {
    element: null,
    root: null,
    owner: null,
    onUnpin: null,
}

let activeRenderId: string | null = null

function createHoverRootForCaller(callerId: string, suppressed: boolean): Root {
    return {
        render: (children: ReactNode): void => {
            if (suppressed) {
                return
            }
            if (hover.owner !== callerId || activeRenderId !== callerId) {
                console.error('[useInsightTooltip] dropped render — caller no longer owns the hover tooltip', {
                    callerId,
                    hoverOwner: hover.owner,
                    activeRenderId,
                    pinnedOwner: pinned.owner,
                })
                return
            }
            hover.lastRendered = children
            hover.lastRenderedOwner = callerId
            hover.root?.render(children)
        },
        unmount: (): void => {
            // the shared hover root is never unmounted; cleanupTooltip clears state instead
        },
    }
}

function clearHoverHideTimeout(): void {
    if (hover.hideTimeout) {
        clearTimeout(hover.hideTimeout)
        hover.hideTimeout = null
    }
}

function clearHoverInteractiveTimeout(): void {
    if (hover.interactiveTimeout) {
        clearTimeout(hover.interactiveTimeout)
        hover.interactiveTimeout = null
    }
}

function disableHoverInteractivity(): void {
    if (hover.element) {
        hover.element.style.pointerEvents = 'none'
    }
    clearHoverInteractiveTimeout()
}

function scheduleHoverInteractivity(): void {
    clearHoverInteractiveTimeout()
    hover.interactiveTimeout = setTimeout(() => {
        if (hover.element) {
            hover.element.style.pointerEvents = 'auto'
        }
        hover.interactiveTimeout = null
    }, INTERACTIVE_DELAY)
}

function hideHoverNow(): void {
    if (hover.element) {
        hover.element.style.opacity = '0'
    }
    disableHoverInteractivity()
}

function onHoverMouseEnter(): void {
    hover.isMouseOver = true
    clearHoverHideTimeout()
}

function onHoverMouseLeave(): void {
    hover.isMouseOver = false
    disableHoverInteractivity()
    clearHoverHideTimeout()
    hover.hideTimeout = setTimeout(() => {
        if (!hover.isMouseOver) {
            hideHoverNow()
        }
    }, HIDE_DELAY)
}

interface SharedTooltipDomOptions {
    id: string
    extraClasses?: string[]
    dataAttr: string
    pointerEvents: 'none' | 'auto'
    attachHoverHandlers: boolean
}

function createSharedTooltipElement(opts: SharedTooltipDomOptions): { element: HTMLElement; root: Root } {
    const element = document.createElement('div')
    element.id = opts.id
    element.classList.add('InsightTooltipWrapper', 'ph-no-capture', ...(opts.extraClasses ?? []))
    element.setAttribute('data-attr', opts.dataAttr)
    element.style.pointerEvents = opts.pointerEvents
    element.style.opacity = '0'
    element.style.position = 'absolute'
    document.body.appendChild(element)
    if (opts.attachHoverHandlers) {
        element.addEventListener('mouseenter', onHoverMouseEnter, { passive: true })
        element.addEventListener('mouseleave', onHoverMouseLeave, { passive: true })
    }
    return { element, root: createRoot(element) }
}

function ensureHoverDom(): void {
    if (hover.element) {
        return
    }
    const { element, root } = createSharedTooltipElement({
        id: 'InsightTooltipWrapper-hover',
        dataAttr: 'insight-tooltip-wrapper',
        pointerEvents: 'none',
        attachHoverHandlers: true,
    })
    hover.element = element
    hover.root = root
}

function ensurePinnedDom(): void {
    if (pinned.element) {
        return
    }
    const { element, root } = createSharedTooltipElement({
        id: 'InsightTooltipWrapper-pinned',
        extraClasses: ['InsightTooltipWrapper--pinned'],
        dataAttr: 'insight-tooltip-wrapper-pinned',
        pointerEvents: 'auto',
        attachHoverHandlers: false,
    })
    pinned.element = element
    pinned.root = root
}

let globalScrollEndListenerActive = false

function initGlobalScrollEndListener(): void {
    if (globalScrollEndListenerActive) {
        return
    }
    globalScrollEndListenerActive = true
    document.addEventListener(
        'scrollend',
        (e) => {
            if (pinned.owner && pinned.element) {
                const scrolledInsidePinned = e.target instanceof Node && pinned.element.contains(e.target as Node)
                if (!scrolledInsidePinned) {
                    unpinTooltip(pinned.owner)
                }
            }
            if (hover.owner && hover.element) {
                const scrolledInsideHover = e.target instanceof Node && hover.element.contains(e.target as Node)
                if (!scrolledInsideHover) {
                    hideTooltip(hover.owner)
                }
            }
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
            if (!pinned.owner || !pinned.element) {
                return
            }
            if (e.target instanceof Node && pinned.element.contains(e.target as Node)) {
                return
            }
            unpinTooltip(pinned.owner)
        },
        { passive: true }
    )

    document.addEventListener(
        'keydown',
        (e) => {
            if (e.key === 'Escape' && pinned.owner) {
                unpinTooltip(pinned.owner)
            }
        },
        { passive: true }
    )
}

export function ensureTooltip(id: string): [Root, HTMLElement] {
    ensureHoverDom()
    clearHoverHideTimeout()
    if (pinned.owner === id) {
        hideHoverNow()
        activeRenderId = null
        return [createHoverRootForCaller(id, true), hover.element!]
    }
    hover.owner = id
    activeRenderId = id
    return [createHoverRootForCaller(id, false), hover.element!]
}

export function showTooltip(id: string): void {
    if (activeRenderId !== id || !hover.element) {
        return
    }
    clearHoverHideTimeout()
    hover.element.style.opacity = '1'
}

export function hideTooltip(id?: string): void {
    if (id && activeRenderId !== id) {
        return
    }
    if (!hover.element) {
        return
    }
    clearHoverHideTimeout()
    if (hover.isMouseOver) {
        return
    }
    hover.hideTimeout = setTimeout(() => {
        if (!hover.isMouseOver) {
            hideHoverNow()
        }
    }, HIDE_DELAY)
}

export function pinTooltip(id: string, onUnpin?: () => void): void {
    if (!hover.element) {
        return
    }
    if (hover.lastRenderedOwner !== id || hover.lastRendered === null) {
        return
    }
    ensurePinnedDom()
    if (pinned.owner && pinned.owner !== id) {
        const previousOnUnpin = pinned.onUnpin
        pinned.onUnpin = null
        previousOnUnpin?.()
    }
    pinned.root?.render(hover.lastRendered)
    if (pinned.element) {
        pinned.element.style.left = hover.element.style.left
        pinned.element.style.top = hover.element.style.top
        pinned.element.style.opacity = '1'
        pinned.element.style.pointerEvents = 'auto'
    }
    pinned.owner = id
    pinned.onUnpin = onUnpin ?? null

    hideHoverNow()
    if (hover.owner === id) {
        hover.owner = null
    }
    activeRenderId = null
}

export function unpinTooltip(id: string): void {
    if (pinned.owner !== id) {
        return
    }
    const callback = pinned.onUnpin
    pinned.onUnpin = null
    pinned.owner = null
    pinned.root?.render(null)
    if (pinned.element) {
        pinned.element.style.opacity = '0'
        pinned.element.style.pointerEvents = 'none'
    }
    callback?.()
}

export function cleanupTooltip(id: string): void {
    if (hover.owner !== id && pinned.owner !== id) {
        return
    }
    if (hover.owner === id) {
        hover.owner = null
        if (activeRenderId === id) {
            activeRenderId = null
        }
        if (hover.lastRenderedOwner === id) {
            hover.lastRendered = null
            hover.lastRenderedOwner = null
            hover.root?.render(null)
        }
        hideHoverNow()
    }
    if (pinned.owner === id) {
        unpinTooltip(id)
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

export function positionTooltipAt(id: string, left: number, top: number): void {
    if (activeRenderId !== id || !hover.element) {
        return
    }
    hover.element.style.position = 'absolute'
    hover.element.style.left = `${left}px`
    hover.element.style.top = `${top}px`
}

export function resetTooltipPosition(id: string): void {
    if (activeRenderId !== id || !hover.element) {
        return
    }
    hover.element.style.left = ''
    hover.element.style.top = ''
}

export function measureTooltip(id: string): DOMRect | null {
    if (activeRenderId !== id || !hover.element) {
        return null
    }
    return hover.element.getBoundingClientRect()
}

export function positionTooltip(
    tooltipEl: HTMLElement,
    canvasBounds: DOMRect,
    caretX: number,
    caretY: number,
    centerVertically = false
): void {
    if (tooltipEl !== hover.element) {
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
    positionTooltipAt: (left: number, top: number) => void
    resetTooltipPosition: () => void
    measureTooltip: () => DOMRect | null
    pinTooltip: ((onUnpin?: () => void) => void) | null
} {
    const isPinnable = options?.isPinnable ?? false
    const tooltipIdRef = useRef<string | null>(null)
    if (tooltipIdRef.current === null) {
        tooltipIdRef.current = Math.random().toString(36).substring(2, 11)
    }
    const tooltipId = tooltipIdRef.current

    useOnMountEffect(() => {
        initGlobalScrollEndListener()
        if (isPinnable) {
            initGlobalUnpinListeners()
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
    const positionAt = useCallback(
        (left: number, top: number): void => positionTooltipAt(tooltipId, left, top),
        [tooltipId]
    )
    const resetPosition = useCallback((): void => resetTooltipPosition(tooltipId), [tooltipId])
    const measure = useCallback((): DOMRect | null => measureTooltip(tooltipId), [tooltipId])

    return {
        tooltipId,
        getTooltip,
        showTooltip: show,
        hideTooltip: hide,
        cleanupTooltip: cleanup,
        positionTooltip,
        positionTooltipAt: positionAt,
        resetTooltipPosition: resetPosition,
        measureTooltip: measure,
        pinTooltip: isPinnable ? pin : null,
    }
}
