import { useCallback, useMemo } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

type TooltipInstance = {
    root: Root
    element: HTMLElement
    isMouseOver: boolean
    hideTimeout: NodeJS.Timeout | null
    interactiveTimeout: NodeJS.Timeout | null
    mouseEnterHandler: () => void
    mouseLeaveHandler: () => void
}

const tooltipInstances = new Map<string, TooltipInstance>()

let globalScrollEndListenerActive = false

function initGlobalScrollEndListener(): void {
    if (globalScrollEndListenerActive) {
        return
    }
    globalScrollEndListenerActive = true
    document.addEventListener(
        'scrollend',
        (e) => {
            // Don't hide when the scroll originated from inside a tooltip
            if (e.target instanceof Node) {
                for (const instance of tooltipInstances.values()) {
                    if (instance.element.contains(e.target as Node)) {
                        return
                    }
                }
            }
            hideTooltip()
        },
        { capture: true, passive: true }
    )
}

/** Time the tooltip must be stationary before it becomes interactive (ms) */
const INTERACTIVE_DELAY = 500

function disableInteractivity(instance: TooltipInstance): void {
    instance.element.style.pointerEvents = 'none'
    if (instance.interactiveTimeout) {
        clearTimeout(instance.interactiveTimeout)
        instance.interactiveTimeout = null
    }
}

function scheduleInteractivity(instance: TooltipInstance): void {
    if (instance.interactiveTimeout) {
        clearTimeout(instance.interactiveTimeout)
    }
    instance.interactiveTimeout = setTimeout(() => {
        instance.element.style.pointerEvents = 'auto'
        instance.interactiveTimeout = null
    }, INTERACTIVE_DELAY)
}

export function ensureTooltip(id: string): [Root, HTMLElement] {
    let instance = tooltipInstances.get(id)

    if (!instance) {
        const tooltipEl = document.createElement('div')
        tooltipEl.id = `InsightTooltipWrapper-${id}`
        tooltipEl.classList.add('InsightTooltipWrapper')
        tooltipEl.setAttribute('data-attr', 'insight-tooltip-wrapper')
        tooltipEl.style.pointerEvents = 'none'
        document.body.appendChild(tooltipEl)

        const root = createRoot(tooltipEl)

        const mouseEnterHandler = (): void => {
            const inst = tooltipInstances.get(id)
            if (inst) {
                inst.isMouseOver = true
                if (inst.hideTimeout) {
                    clearTimeout(inst.hideTimeout)
                    inst.hideTimeout = null
                }
            }
        }

        const mouseLeaveHandler = (): void => {
            const inst = tooltipInstances.get(id)
            if (inst) {
                inst.isMouseOver = false
                disableInteractivity(inst)
                inst.hideTimeout = setTimeout(() => {
                    if (!inst.isMouseOver) {
                        inst.element.style.opacity = '0'
                    }
                }, 100)
            }
        }

        instance = {
            root,
            element: tooltipEl,
            isMouseOver: false,
            hideTimeout: null,
            interactiveTimeout: null,
            mouseEnterHandler,
            mouseLeaveHandler,
        }

        tooltipInstances.set(id, instance)

        tooltipEl.addEventListener('mouseenter', mouseEnterHandler, { passive: true })
        tooltipEl.addEventListener('mouseleave', mouseLeaveHandler, { passive: true })
    }

    return [instance.root, instance.element]
}

export function showTooltip(id: string): void {
    const instance = tooltipInstances.get(id)
    if (!instance) {
        return
    }

    // Cancel any pending hide so a returning mouse doesn't get hidden
    if (instance.hideTimeout) {
        clearTimeout(instance.hideTimeout)
        instance.hideTimeout = null
    }

    instance.element.style.opacity = '1'
}

export function hideTooltip(id?: string): void {
    if (!id) {
        // Fallback to old behavior - hide all tooltips
        tooltipInstances.forEach((instance) => {
            instance.element.style.opacity = '0'
            disableInteractivity(instance)
        })
        return
    }

    const instance = tooltipInstances.get(id)
    if (!instance) {
        return
    }

    if (instance.hideTimeout) {
        clearTimeout(instance.hideTimeout)
        instance.hideTimeout = null
    }

    if (instance.isMouseOver) {
        return
    }

    instance.hideTimeout = setTimeout(() => {
        if (!instance.isMouseOver) {
            instance.element.style.opacity = '0'
            disableInteractivity(instance)
        }
    }, 100)
}

export function cleanupTooltip(id: string): void {
    const instance = tooltipInstances.get(id)
    if (instance) {
        if (instance.hideTimeout) {
            clearTimeout(instance.hideTimeout)
        }
        disableInteractivity(instance)
        instance.element.removeEventListener('mouseenter', instance.mouseEnterHandler)
        instance.element.removeEventListener('mouseleave', instance.mouseLeaveHandler)
        tooltipInstances.delete(id)
        queueMicrotask(() => {
            instance.root.unmount()
            instance.element.remove()
        })
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
    tooltipEl.style.position = 'absolute'
    tooltipEl.style.maxWidth = ''

    // Each reposition means the mouse is still moving — reset interactivity timer
    const id = tooltipEl.id.replace('InsightTooltipWrapper-', '')
    const instance = tooltipInstances.get(id)
    if (instance) {
        disableInteractivity(instance)
        scheduleInteractivity(instance)
    }

    applyPosition(tooltipEl, canvasBounds, caretX, caretY, centerVertically)

    // On first render offsetWidth may be 0 since content hasn't painted yet.
    // Re-run positioning after paint so boundary clamping uses real dimensions.
    if (tooltipEl.offsetWidth === 0) {
        requestAnimationFrame(() => {
            applyPosition(tooltipEl, canvasBounds, caretX, caretY, centerVertically)
        })
    }
}

export function useInsightTooltip(): {
    tooltipId: string
    getTooltip: () => [Root, HTMLElement]
    showTooltip: () => void
    hideTooltip: () => void
    cleanupTooltip: () => void
    positionTooltip: typeof positionTooltip
} {
    const tooltipId = useMemo(() => Math.random().toString(36).substring(2, 11), [])

    useOnMountEffect(() => {
        initGlobalScrollEndListener()
        return () => {
            cleanupTooltip(tooltipId)
        }
    })

    const getTooltip = useCallback((): [Root, HTMLElement] => ensureTooltip(tooltipId), [tooltipId])
    const show = useCallback((): void => showTooltip(tooltipId), [tooltipId])
    const hide = useCallback((): void => hideTooltip(tooltipId), [tooltipId])
    const cleanup = useCallback((): void => cleanupTooltip(tooltipId), [tooltipId])

    return { tooltipId, getTooltip, showTooltip: show, hideTooltip: hide, cleanupTooltip: cleanup, positionTooltip }
}
