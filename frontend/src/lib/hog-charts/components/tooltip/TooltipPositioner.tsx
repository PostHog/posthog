import type React from 'react'
import { useLayoutEffect, useRef, useState } from 'react'

import type { TooltipContext } from '../../types'

export function TooltipPositioner({
    context,
    containerRef,
    children,
}: {
    context: TooltipContext
    containerRef: React.RefObject<HTMLElement>
    children: React.ReactNode
}): JSX.Element {
    const tooltipRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number }>({ left: 0, top: 0 })

    useLayoutEffect(() => {
        if (!tooltipRef.current || !containerRef.current) {
            return
        }

        const tooltip = tooltipRef.current
        const bounds = context.chartBounds
        const caretX = bounds.left + window.scrollX + context.position.x
        const caretY = bounds.top + window.scrollY + context.position.y

        let left = caretX + 12
        const top = caretY - tooltip.offsetHeight / 2

        const viewportRight = window.scrollX + document.documentElement.clientWidth
        if (tooltip.offsetWidth > 0 && left + tooltip.offsetWidth > viewportRight - 8) {
            left = caretX - tooltip.offsetWidth - 12
        }

        left = Math.max(window.scrollX + 8, left)
        const viewportBottom = window.scrollY + document.documentElement.clientHeight
        const clampedTop = Math.min(
            Math.max(window.scrollY + 8, top),
            viewportBottom - Math.max(tooltip.offsetHeight, 0) - 8
        )

        setPosition({ left, top: clampedTop })
    }, [context, containerRef])

    return (
        <div
            ref={tooltipRef}
            className="absolute z-50 pointer-events-none transition-[opacity,left,top] duration-150 ease-out"
            style={{ left: position.left, top: position.top }}
        >
            {children}
        </div>
    )
}
