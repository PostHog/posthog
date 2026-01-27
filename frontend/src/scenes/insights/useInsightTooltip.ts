import { useCallback, useMemo } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

type TooltipInstance = {
    root: Root
    element: HTMLElement
    isMouseOver: boolean
    hideTimeout: NodeJS.Timeout | null
    mouseEnterHandler: () => void
    mouseLeaveHandler: () => void
}

const tooltipInstances = new Map<string, TooltipInstance>()

export function ensureTooltip(id: string): [Root, HTMLElement] {
    let instance = tooltipInstances.get(id)

    if (!instance) {
        const tooltipEl = document.createElement('div')
        tooltipEl.id = `InsightTooltipWrapper-${id}`
        tooltipEl.classList.add('InsightTooltipWrapper')
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
                inst.hideTimeout = setTimeout(() => {
                    if (!inst.isMouseOver) {
                        inst.element.classList.add('opacity-0', 'invisible')
                    }
                }, 100)
            }
        }

        instance = {
            root,
            element: tooltipEl,
            isMouseOver: false,
            hideTimeout: null,
            mouseEnterHandler,
            mouseLeaveHandler,
        }

        tooltipInstances.set(id, instance)

        tooltipEl.addEventListener('mouseenter', mouseEnterHandler, { passive: true })
        tooltipEl.addEventListener('mouseleave', mouseLeaveHandler, { passive: true })
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
        instance.element.removeEventListener('mouseenter', instance.mouseEnterHandler)
        instance.element.removeEventListener('mouseleave', instance.mouseLeaveHandler)
        tooltipInstances.delete(id)
        queueMicrotask(() => {
            instance.root.unmount()
            instance.element.remove()
        })
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

    const getTooltip = useCallback((): [Root, HTMLElement] => ensureTooltip(tooltipId), [tooltipId])
    const hide = useCallback((): void => hideTooltip(tooltipId), [tooltipId])
    const cleanup = useCallback((): void => cleanupTooltip(tooltipId), [tooltipId])

    return { tooltipId, getTooltip, hideTooltip: hide, cleanupTooltip: cleanup }
}
