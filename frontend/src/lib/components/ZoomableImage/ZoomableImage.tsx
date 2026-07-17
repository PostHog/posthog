import { useCallback, useEffect, useRef, useState } from 'react'

import { IconMinus, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

const MIN_SCALE = 1
const MAX_SCALE = 8
const ZOOM_STEP = 0.5
const WHEEL_ZOOM_SENSITIVITY = 0.006 // effective sensitivity per pixel of deltaY

interface Transform {
    scale: number
    x: number
    y: number
}

const DEFAULT_TRANSFORM: Transform = { scale: 1, x: 0, y: 0 }

const clamp = (value: number, min: number, max: number): number => Math.min(Math.max(value, min), max)

export interface ZoomableImageProps {
    src: string
    alt: string
    /** Resets zoom/pan back to the default whenever this value changes (e.g. switching images). */
    resetKey?: string | number
    className?: string
}

/**
 * An image that can be zoomed (wheel / buttons / double-click) and panned by dragging.
 * Useful for inspecting large screenshots where the detail matters.
 */
export function ZoomableImage({ src, alt, resetKey, className }: ZoomableImageProps): JSX.Element {
    const [transform, setTransform] = useState<Transform>(DEFAULT_TRANSFORM)
    const dragState = useRef<{
        pointerId: number
        startX: number
        startY: number
        originX: number
        originY: number
    } | null>(null)

    // Reset when the source image changes so each image starts fresh.
    useEffect(() => {
        setTransform(DEFAULT_TRANSFORM)
    }, [src, resetKey])

    const zoomBy = useCallback((delta: number): void => {
        setTransform((prev) => {
            const nextScale = clamp(prev.scale + delta, MIN_SCALE, MAX_SCALE)
            if (nextScale === MIN_SCALE) {
                return DEFAULT_TRANSFORM
            }
            // Keep the current pan but scale it proportionally so the view stays centered.
            const ratio = nextScale / prev.scale
            return { scale: nextScale, x: prev.x * ratio, y: prev.y * ratio }
        })
    }, [])

    const handleWheel = useCallback(
        (e: React.WheelEvent): void => {
            e.preventDefault()
            zoomBy(-e.deltaY * WHEEL_ZOOM_SENSITIVITY)
        },
        [zoomBy]
    )

    const reset = useCallback((): void => setTransform(DEFAULT_TRANSFORM), [])

    const handlePointerDown = useCallback(
        (e: React.PointerEvent): void => {
            if (transform.scale <= MIN_SCALE) {
                return
            }
            e.preventDefault()
            ;(e.target as Element).setPointerCapture(e.pointerId)
            dragState.current = {
                pointerId: e.pointerId,
                startX: e.clientX,
                startY: e.clientY,
                originX: transform.x,
                originY: transform.y,
            }
        },
        [transform]
    )

    const handlePointerMove = useCallback((e: React.PointerEvent): void => {
        const drag = dragState.current
        if (!drag || drag.pointerId !== e.pointerId) {
            return
        }
        setTransform((prev) => ({
            ...prev,
            x: drag.originX + (e.clientX - drag.startX),
            y: drag.originY + (e.clientY - drag.startY),
        }))
    }, [])

    const endDrag = useCallback((e: React.PointerEvent): void => {
        if (dragState.current?.pointerId === e.pointerId) {
            dragState.current = null
        }
    }, [])

    const toggleZoom = useCallback((): void => {
        setTransform((prev) => (prev.scale > MIN_SCALE ? DEFAULT_TRANSFORM : { scale: 2, x: 0, y: 0 }))
    }, [])

    const isZoomed = transform.scale > MIN_SCALE

    return (
        <div className={`relative flex flex-col items-stretch ${className ?? ''}`}>
            <div
                className="relative flex-1 flex items-center justify-center overflow-hidden bg-bg-light rounded select-none"
                onWheel={handleWheel}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onDoubleClick={toggleZoom}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ cursor: isZoomed ? (dragState.current ? 'grabbing' : 'grab') : 'zoom-in' }}
            >
                <img
                    src={src}
                    alt={alt}
                    draggable={false}
                    className="max-w-full max-h-full object-contain"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
                        transition: dragState.current ? 'none' : 'transform 0.1s ease-out',
                    }}
                />
            </div>
            <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-surface-primary/90 rounded px-1 py-0.5 shadow-md backdrop-blur z-10">
                <LemonButton
                    icon={<IconMinus />}
                    size="small"
                    onClick={() => zoomBy(-ZOOM_STEP)}
                    disabledReason={transform.scale <= MIN_SCALE ? 'Already at minimum zoom' : undefined}
                    tooltip="Zoom out"
                    noPadding
                />
                <span className="text-xs font-semibold tabular-nums w-12 text-center">
                    {Math.round(transform.scale * 100)}%
                </span>
                <LemonButton
                    icon={<IconPlus />}
                    size="small"
                    onClick={() => zoomBy(ZOOM_STEP)}
                    disabledReason={transform.scale >= MAX_SCALE ? 'Already at maximum zoom' : undefined}
                    tooltip="Zoom in"
                    noPadding
                />
                <LemonButton
                    icon={<IconRefresh />}
                    size="small"
                    onClick={reset}
                    disabledReason={!isZoomed ? 'Nothing to reset' : undefined}
                    tooltip="Reset zoom"
                    noPadding
                />
            </div>
        </div>
    )
}
