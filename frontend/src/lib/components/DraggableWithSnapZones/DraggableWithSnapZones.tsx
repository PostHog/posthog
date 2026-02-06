import clsx from 'clsx'
import { ReactElement, forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import Draggable, { DraggableData, DraggableEvent } from 'react-draggable'

export type SnapPosition =
    | 'top-left'
    | 'top-center'
    | 'top-right'
    | 'left-center'
    | 'right-center'
    | 'bottom-left'
    | 'bottom-center'
    | 'bottom-right'

const ALL_SNAP_POSITIONS: SnapPosition[] = [
    'top-left',
    'top-center',
    'top-right',
    'left-center',
    'right-center',
    'bottom-left',
    'bottom-center',
    'bottom-right',
]

const DEFAULT_SNAP_THRESHOLD = 100
const DEFAULT_PADDING = 16

interface PersistedState {
    snapPosition: SnapPosition | null
    freePosition: { x: number; y: number } | null
}

function loadPersistedState(key: string): PersistedState | null {
    try {
        const stored = localStorage.getItem(key)
        if (stored) {
            return JSON.parse(stored)
        }
    } catch {
        // Ignore parse errors
    }
    return null
}

function persistState(key: string, state: PersistedState): void {
    try {
        localStorage.setItem(key, JSON.stringify(state))
    } catch {
        // Ignore storage errors
    }
}

function getSnapZonePositions(width: number, height: number): Record<SnapPosition, { x: number; y: number }> {
    return {
        'top-left': { x: 0, y: 0 },
        'top-center': { x: width / 2, y: 0 },
        'top-right': { x: width, y: 0 },
        'left-center': { x: 0, y: height / 2 },
        'right-center': { x: width, y: height / 2 },
        'bottom-left': { x: 0, y: height },
        'bottom-center': { x: width / 2, y: height },
        'bottom-right': { x: width, y: height },
    }
}

function snapPositionToCoords(
    snapPosition: SnapPosition,
    windowWidth: number,
    windowHeight: number,
    elementWidth: number,
    elementHeight: number,
    padding: number
): { x: number; y: number } {
    // Returns top-left corner position for the element
    const positions: Record<SnapPosition, { x: number; y: number }> = {
        'top-left': { x: padding, y: padding },
        'top-center': { x: (windowWidth - elementWidth) / 2, y: padding },
        'top-right': { x: windowWidth - elementWidth - padding, y: padding },
        'left-center': { x: padding, y: (windowHeight - elementHeight) / 2 },
        'right-center': { x: windowWidth - elementWidth - padding, y: (windowHeight - elementHeight) / 2 },
        'bottom-left': { x: padding, y: windowHeight - elementHeight - padding },
        'bottom-center': { x: (windowWidth - elementWidth) / 2, y: windowHeight - elementHeight - padding },
        'bottom-right': { x: windowWidth - elementWidth - padding, y: windowHeight - elementHeight - padding },
    }

    return positions[snapPosition]
}

function findNearestSnapZone(
    x: number,
    y: number,
    allowedPositions: SnapPosition[],
    windowWidth: number,
    windowHeight: number,
    elementWidth: number,
    elementHeight: number,
    padding: number,
    threshold: number
): SnapPosition | null {
    for (const position of allowedPositions) {
        const snapCoords = snapPositionToCoords(
            position,
            windowWidth,
            windowHeight,
            elementWidth,
            elementHeight,
            padding
        )
        const distance = Math.hypot(x - snapCoords.x, y - snapCoords.y)
        if (distance < threshold) {
            return position
        }
    }
    return null
}

interface SnapZoneIndicatorProps {
    position: { x: number; y: number }
    isActive: boolean
    size: number
}

function SnapZoneIndicator({ position, isActive, size }: SnapZoneIndicatorProps): JSX.Element {
    return (
        <div
            className={clsx(
                'transition-all absolute rounded-lg border-2',
                isActive ? 'bg-primary/40 border-primary shadow-lg' : 'bg-primary/25 border-primary/50'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: position.x,
                top: position.y,
                marginLeft: -size * 0.5,
                marginTop: -size * 0.5,
                width: size,
                height: size,
                transform: isActive ? 'scale(1.3)' : 'scale(1)',
            }}
        />
    )
}

interface SnapZonesOverlayProps {
    snapZones: Record<SnapPosition, { x: number; y: number }>
    activePosition: SnapPosition | null
    size: number
}

function SnapZonesOverlay({ snapZones, activePosition, size }: SnapZonesOverlayProps): JSX.Element {
    return (
        <div className="w-full h-full fixed inset-0 pointer-events-none overflow-hidden z-[var(--z-modal)]">
            {Object.entries(snapZones).map(([key, pos]) => (
                <SnapZoneIndicator key={key} position={pos} isActive={key === activePosition} size={size} />
            ))}
        </div>
    )
}

export interface DraggableWithSnapZonesProps {
    /** The draggable content - must be a single element that accepts a ref */
    children: ReactElement
    /** CSS selector for the drag handle within children */
    handle?: string
    /** Default snap position when first rendered */
    defaultSnapPosition?: SnapPosition
    /** Which snap positions to allow. Defaults to all 8. */
    allowedPositions?: SnapPosition[]
    /** Distance in pixels to trigger snap. Defaults to 100. */
    snapThreshold?: number
    /** Padding from viewport edges. Defaults to 16. */
    padding?: number
    /** LocalStorage key for persisting position */
    persistKey?: string
    /** Callback when dragging starts */
    onDragStart?: () => void
    /** Callback when dragging ends */
    onDragStop?: () => void
}

export interface DraggableWithSnapZonesRef {
    /** Snap to a position only if not already snapped somewhere */
    trySnapTo: (position: SnapPosition) => void
}

export const DraggableWithSnapZones = forwardRef<DraggableWithSnapZonesRef, DraggableWithSnapZonesProps>(
    function DraggableWithSnapZones(
        {
            children,
            handle,
            defaultSnapPosition = 'bottom-right',
            allowedPositions = ALL_SNAP_POSITIONS,
            snapThreshold = DEFAULT_SNAP_THRESHOLD,
            padding = DEFAULT_PADDING,
            persistKey,
            onDragStart,
            onDragStop,
        },
        ref
    ) {
        const nodeRef = useRef<HTMLDivElement>(null)

        const [windowSize, setWindowSize] = useState({ width: window.innerWidth, height: window.innerHeight })
        const [isDragging, setIsDragging] = useState(false)

        // Load persisted state or use defaults
        const [snapPosition, setSnapPosition] = useState<SnapPosition | null>(() => {
            if (persistKey) {
                const persisted = loadPersistedState(persistKey)
                if (persisted) {
                    return persisted.snapPosition
                }
            }
            return defaultSnapPosition
        })

        const [freePosition, setFreePosition] = useState<{ x: number; y: number } | null>(() => {
            if (persistKey) {
                const persisted = loadPersistedState(persistKey)
                if (persisted) {
                    return persisted.freePosition
                }
            }
            return null
        })

        // Track the current drag position for controlled positioning (starts at 0,0, hidden until measured)
        const [dragPosition, setDragPosition] = useState({ x: 0, y: 0 })

        // Track element dimensions (needed for initial position calculation)
        const [elementSize, setElementSize] = useState<{ width: number; height: number } | null>(null)

        // Expose imperative methods via ref
        useImperativeHandle(
            ref,
            () => ({
                trySnapTo: (targetPosition: SnapPosition) => {
                    // Only snap if not already snapped to a position
                    if (snapPosition !== null) {
                        return
                    }

                    const width = elementSize?.width ?? 0
                    const height = elementSize?.height ?? 0

                    const coords = snapPositionToCoords(
                        targetPosition,
                        windowSize.width,
                        windowSize.height,
                        width,
                        height,
                        padding
                    )

                    setSnapPosition(targetPosition)
                    setFreePosition(null)
                    setDragPosition(coords)

                    if (persistKey) {
                        persistState(persistKey, { snapPosition: targetPosition, freePosition: null })
                    }
                },
            }),
            [snapPosition, elementSize, windowSize.width, windowSize.height, padding, persistKey]
        )

        // Update window size on resize
        useEffect(() => {
            const handleResize = (): void => {
                setWindowSize({ width: window.innerWidth, height: window.innerHeight })
            }
            window.addEventListener('resize', handleResize)
            return () => window.removeEventListener('resize', handleResize)
        }, [])

        // Measure element after mount using ResizeObserver for accuracy
        useEffect(() => {
            const element = nodeRef.current
            if (!element) {
                return
            }

            const updateSize = (): void => {
                setElementSize({
                    width: element.offsetWidth,
                    height: element.offsetHeight,
                })
            }

            const observer = new ResizeObserver(updateSize)
            observer.observe(element)
            updateSize()

            return () => observer.disconnect()
        }, [])

        const snapZones = useMemo(
            () => getSnapZonePositions(windowSize.width, windowSize.height),
            [windowSize.width, windowSize.height]
        )

        // Calculate the actual position based on snap or free position
        const position = useMemo(() => {
            // Use fallback dimensions until measured (element hidden until then anyway)
            const width = elementSize?.width ?? 0
            const height = elementSize?.height ?? 0

            if (freePosition) {
                return freePosition
            }

            if (snapPosition) {
                return snapPositionToCoords(snapPosition, windowSize.width, windowSize.height, width, height, padding)
            }

            return snapPositionToCoords(
                defaultSnapPosition,
                windowSize.width,
                windowSize.height,
                width,
                height,
                padding
            )
        }, [freePosition, snapPosition, windowSize.width, windowSize.height, padding, defaultSnapPosition, elementSize])

        // Update drag position when calculated position changes (for controlled mode)
        useEffect(() => {
            if (!isDragging) {
                setDragPosition(position)
            }
        }, [position, isDragging])

        const handleDragStart = (): void => {
            setIsDragging(true)
            onDragStart?.()
        }

        const handleDrag = (_e: DraggableEvent, data: DraggableData): void => {
            if (!nodeRef.current) {
                return
            }

            const elementWidth = nodeRef.current.offsetWidth
            const elementHeight = nodeRef.current.offsetHeight

            const nearestSnap = findNearestSnapZone(
                data.x,
                data.y,
                allowedPositions,
                windowSize.width,
                windowSize.height,
                elementWidth,
                elementHeight,
                padding,
                snapThreshold
            )
            setSnapPosition(nearestSnap)
            setDragPosition({ x: data.x, y: data.y })
        }

        const handleDragStop = (_e: DraggableEvent, data: DraggableData): void => {
            setIsDragging(false)

            if (!nodeRef.current) {
                onDragStop?.()
                return
            }

            const elementWidth = nodeRef.current.offsetWidth
            const elementHeight = nodeRef.current.offsetHeight

            const nearestSnap = findNearestSnapZone(
                data.x,
                data.y,
                allowedPositions,
                windowSize.width,
                windowSize.height,
                elementWidth,
                elementHeight,
                padding,
                snapThreshold
            )

            if (nearestSnap) {
                setSnapPosition(nearestSnap)
                setFreePosition(null)
                const snappedCoords = snapPositionToCoords(
                    nearestSnap,
                    windowSize.width,
                    windowSize.height,
                    elementWidth,
                    elementHeight,
                    padding
                )
                setDragPosition(snappedCoords)
                if (persistKey) {
                    persistState(persistKey, { snapPosition: nearestSnap, freePosition: null })
                }
            } else {
                setSnapPosition(null)
                setFreePosition({ x: data.x, y: data.y })
                if (persistKey) {
                    persistState(persistKey, { snapPosition: null, freePosition: { x: data.x, y: data.y } })
                }
            }

            onDragStop?.()
        }

        return (
            <>
                {isDragging && (
                    <SnapZonesOverlay snapZones={snapZones} activePosition={snapPosition} size={snapThreshold} />
                )}
                <Draggable
                    nodeRef={nodeRef}
                    handle={handle}
                    position={dragPosition}
                    onStart={handleDragStart}
                    onDrag={handleDrag}
                    onStop={handleDragStop}
                >
                    <div
                        ref={nodeRef}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'fixed',
                            top: 0,
                            left: 0,
                            zIndex: 'var(--z-modal)',
                            visibility: elementSize ? 'visible' : 'hidden',
                        }}
                    >
                        {children}
                    </div>
                </Draggable>
            </>
        )
    }
)
