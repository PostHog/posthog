import React, { useCallback, useEffect, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

type ResizableElementProps = {
    defaultWidth: number
    minWidth?: number
    maxWidth?: number
    onResize: (width: number) => void
    children?: React.ReactNode
    className?: string
    innerClassName?: string
    style?: React.CSSProperties
    borderPosition?: 'center' | 'left' | 'right'
    onResizeStart?: () => void
    onResizeEnd?: () => void
}

export function ResizableElement({
    defaultWidth,
    minWidth = 100,
    maxWidth = 1000,
    onResize,
    children,
    className,
    innerClassName,
    style,
    borderPosition = 'center',
    onResizeStart,
    onResizeEnd,
    ...props
}: ResizableElementProps): JSX.Element {
    const [width, setWidth] = useState(defaultWidth)
    const containerRef = useRef<HTMLDivElement>(null)
    const startXRef = useRef<number>(0)
    const startWidthRef = useRef<number>(0)
    const isResizing = useRef(false)
    const rafRef = useRef<number | null>(null)
    const currentWidthRef = useRef(defaultWidth)

    // Update the current width ref when state changes
    useEffect(() => {
        currentWidthRef.current = width
    }, [width])

    // Function to apply width directly to DOM for smoother resizing
    const applyWidth = useCallback((newWidth: number) => {
        if (containerRef.current) {
            containerRef.current.style.width = `${newWidth}px`
        }
        currentWidthRef.current = newWidth
    }, [])

    const handleMouseDown = useCallback(
        (e: React.MouseEvent | React.TouchEvent) => {
            document.body.classList.add('is-resizing')
            const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
            startXRef.current = clientX
            startWidthRef.current = currentWidthRef.current
            isResizing.current = true
            e.preventDefault()
            onResizeStart?.()
        },
        [onResizeStart]
    )

    const handleMove = useCallback(
        (clientX: number) => {
            if (!isResizing.current) {
                return
            }

            // Cancel any ongoing animation frame
            if (rafRef.current !== null) {
                cancelAnimationFrame(rafRef.current)
            }

            // Schedule a new frame for smooth animation
            rafRef.current = requestAnimationFrame(() => {
                // Calculate the difference from start position
                const deltaX = clientX - startXRef.current

                // Apply the delta to the starting width
                const newWidth = Math.min(Math.max(startWidthRef.current + deltaX, minWidth), maxWidth)

                // Apply width directly to DOM for smoother animation
                applyWidth(newWidth)

                // Call onResize callback but not setState (we'll do that on mouseup)
                onResize(newWidth)

                rafRef.current = null
            })
        },
        [applyWidth, maxWidth, minWidth, onResize]
    )

    const handleMouseMove = useCallback(
        (e: MouseEvent) => {
            handleMove(e.clientX)
        },
        [handleMove]
    )

    const handleTouchMove = useCallback(
        (e: TouchEvent) => {
            handleMove(e.touches[0].clientX)
        },
        [handleMove]
    )

    const handleEnd = useCallback(() => {
        if (isResizing.current) {
            // Only update React state once at the end of resize
            setWidth(currentWidthRef.current)
            isResizing.current = false

            // Clean up any pending animation frame
            if (rafRef.current !== null) {
                cancelAnimationFrame(rafRef.current)
                rafRef.current = null
            }
            document.body.classList.remove('is-resizing')
            onResizeEnd?.()
        }
    }, [onResizeEnd])

    // Use effect for adding/removing global event listeners
    useEffect(() => {
        document.addEventListener('mousemove', handleMouseMove)
        document.addEventListener('mouseup', handleEnd)
        document.addEventListener('touchmove', handleTouchMove)
        document.addEventListener('touchend', handleEnd)

        return () => {
            document.removeEventListener('mousemove', handleMouseMove)
            document.removeEventListener('mouseup', handleEnd)
            document.removeEventListener('touchmove', handleTouchMove)
            document.removeEventListener('touchend', handleEnd)

            // Clean up any pending animation frame
            if (rafRef.current !== null) {
                cancelAnimationFrame(rafRef.current)
            }
        }
    }, [handleEnd, handleMouseMove, handleTouchMove])

    return (
        <div
            ref={containerRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width, ...style }}
            className={cn('relative', className)}
        >
            {children}
            <div
                onMouseDown={handleMouseDown}
                onTouchStart={handleMouseDown}
                className={cn(
                    'absolute top-0 right-0 w-1 h-full cursor-ew-resize w-[var(--resizer-thickness)] touch-none overflow-hidden hover:bg-accent-highlight-primary after:content-[""] after:absolute after:top-0 after:w-[1px] after:h-full after:bg-border-primary after:-translate-x-1/2 after:left-1/2',
                    {
                        'bg-accent-highlight-primary': isResizing.current,
                        'after:left-0': borderPosition === 'left',
                        'after:left-full': borderPosition === 'right',
                    },
                    innerClassName
                )}
                role="separator"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                        e.preventDefault()
                        const delta = e.key === 'ArrowLeft' ? -10 : 10
                        const newWidth = Math.min(Math.max(width + delta, minWidth), maxWidth)
                        setWidth(newWidth)
                        applyWidth(newWidth)
                        onResize(newWidth)
                    }
                }}
                {...props}
            />
        </div>
    )
}
