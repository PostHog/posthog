import { useMemo } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const tooltipInstances = new Map<
    string,
    { root: Root; element: HTMLElement; isMouseOver: boolean; hideTimeout: NodeJS.Timeout | null }
>()

export function ensureTooltip(id: string): [Root, HTMLElement] {
    let instance = tooltipInstances.get(id)

    if (!instance) {
        const tooltipEl = document.createElement('div')
        tooltipEl.id = `InsightTooltipWrapper-${id}`
        tooltipEl.classList.add('InsightTooltipWrapper')
        document.body.appendChild(tooltipEl)

        const root = createRoot(tooltipEl)

        instance = {
            root,
            element: tooltipEl,
            isMouseOver: false,
            hideTimeout: null,
        }

        tooltipInstances.set(id, instance)

        // Add mouse tracking for this specific tooltip
        tooltipEl.addEventListener(
            'mouseenter',
            () => {
                instance!.isMouseOver = true
                if (instance!.hideTimeout) {
                    clearTimeout(instance!.hideTimeout)
                    instance!.hideTimeout = null
                }
            },
            { passive: true }
        )

        tooltipEl.addEventListener(
            'mouseleave',
            () => {
                instance!.isMouseOver = false
                instance!.hideTimeout = setTimeout(() => {
                    if (!instance!.isMouseOver) {
                        instance!.element.classList.add('opacity-0', 'invisible')
                    }
                }, 100)
            },
            { passive: true }
        )
    }

    return [instance.root, instance.element]
}

export function hideTooltip(id?: string): void {
    if (!id) {
        // Fallback to old behavior - hide all tooltips
        tooltipInstances.forEach((instance) => {
            instance.element.style.opacity = '0'
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
            instance.element.classList.add('opacity-0', 'invisible')
        }
    }, 100)
}

export function cleanupTooltip(id: string): void {
    const instance = tooltipInstances.get(id)
    if (instance) {
        if (instance.hideTimeout) {
            clearTimeout(instance.hideTimeout)
        }
        queueMicrotask(() => {
            instance.root.unmount()
            instance.element.remove()
        })
        tooltipInstances.delete(id)
    }
}

export function useInsightTooltip(): {
    tooltipId: string
    getTooltip: () => [Root, HTMLElement]
    hideTooltip: () => void
    cleanupTooltip: () => void
} {
    const tooltipId = useMemo(() => Math.random().toString(36).substring(2, 11), [])

    // Clean up tooltip on unmount
    useOnMountEffect(() => {
        return () => {
            cleanupTooltip(tooltipId)
        }
    })

    const getTooltip = (): [Root, HTMLElement] => ensureTooltip(tooltipId)
    const hide = (): void => hideTooltip(tooltipId)
    const cleanup = (): void => cleanupTooltip(tooltipId)

    return { tooltipId, getTooltip, hideTooltip: hide, cleanupTooltip: cleanup }
}
