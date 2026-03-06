import { type ReactElement, type ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { cn } from '../utils'

export interface TooltipProps {
    content: string
    children: ReactNode
    position?: 'top' | 'bottom'
    forceVisible?: boolean
    className?: string
}

export function Tooltip({ content, children, position = 'top', forceVisible, className }: TooltipProps): ReactElement {
    const wrapperRef = useRef<HTMLSpanElement>(null)
    const tooltipRef = useRef<HTMLSpanElement>(null)
    const [left, setLeft] = useState<number | null>(null)

    const reposition = useCallback(() => {
        const wrapper = wrapperRef.current
        const tooltip = tooltipRef.current
        if (!wrapper || !tooltip) {
            return
        }

        const wrapperRect = wrapper.getBoundingClientRect()
        const tooltipWidth = tooltip.offsetWidth
        const pad = 8

        // Center the tooltip over the trigger
        let x = (wrapperRect.width - tooltipWidth) / 2

        // Clamp to viewport edges
        const absLeft = wrapperRect.left + x
        const absRight = absLeft + tooltipWidth
        if (absLeft < pad) {
            x += pad - absLeft
        } else if (absRight > window.innerWidth - pad) {
            x -= absRight - (window.innerWidth - pad)
        }

        setLeft(x)
    }, [])

    useEffect(() => {
        if (forceVisible) {
            reposition()
        }
    }, [forceVisible, reposition])

    return (
        <div className="inline-block">
            <span
                ref={wrapperRef}
                className={cn('relative inline-flex group/tooltip', className)}
                onMouseEnter={reposition}
            >
                {children}
                <span
                    ref={tooltipRef}
                    role="tooltip"
                    style={{ left: left ?? 0 }}
                    className={cn(
                        'pointer-events-none absolute z-10',
                        'rounded-md bg-text-primary text-text-inverse px-2 py-1',
                        'text-xs leading-tight whitespace-nowrap',
                        forceVisible ? 'opacity-100' : 'opacity-0 transition-opacity group-hover/tooltip:opacity-100',
                        position === 'top' && 'bottom-full mb-1.5',
                        position === 'bottom' && 'top-full mt-1.5'
                    )}
                >
                    {content}
                </span>
            </span>
        </div>
    )
}
