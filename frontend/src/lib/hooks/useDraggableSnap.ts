import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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

const DEFAULT_HITBOX_SIZE = 100
const DEFAULT_PADDING = 16
const DRAG_THRESHOLD = 5

export interface DraggableSnapOptions {
    /** Default snap position when first rendered */
    defaultPosition?: SnapPosition
    /** Which snap positions to allow. Defaults to all 8. */
    allowedPositions?: SnapPosition[]
    /** Distance in pixels to trigger snap. Defaults to 100. */
    hitboxSize?: number
    /** Padding from viewport edges. Defaults to 16. */
    padding?: number
    /** LocalStorage key for persisting position. */
    persistKey?: string
}

interface PersistedState {
    fixedPosition: SnapPosition | null
    dragPosition: { x: number; y: number } | null
}

export interface DraggableSnapResult {
    /** Current position in pixels */
    position: { x: number; y: number }
    /** Whether currently being dragged */
    isDragging: boolean
    /** Current snap position, or null if freely positioned */
    fixedPosition: SnapPosition | null
    /** Event handlers to attach to the draggable element's drag handle */
    handlers: {
        onMouseDown: (e: React.MouseEvent) => void
        onTouchStart: (e: React.TouchEvent) => void
    }
    /** All snap zone positions for rendering visual indicators */
    snapZones: Record<SnapPosition, { x: number; y: number }>
    /** Ref setter to attach to the draggable element */
    setElement: (element: HTMLElement | null) => void
}

function inBounds(min: number, value: number, max: number): number {
    return Math.max(min, Math.min(max, value))
}

function getSnapZones(windowWidth: number, windowHeight: number): Record<SnapPosition, { x: number; y: number }> {
    return {
        'top-left': { x: 0, y: 0 },
        'top-center': { x: windowWidth / 2, y: 0 },
        'top-right': { x: windowWidth, y: 0 },
        'left-center': { x: 0, y: windowHeight / 2 },
        'right-center': { x: windowWidth, y: windowHeight / 2 },
        'bottom-left': { x: 0, y: windowHeight },
        'bottom-center': { x: windowWidth / 2, y: windowHeight },
        'bottom-right': { x: windowWidth, y: windowHeight },
    }
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

export function useDraggableSnap(options: DraggableSnapOptions = {}): DraggableSnapResult {
    const {
        defaultPosition = 'bottom-right',
        allowedPositions = ALL_SNAP_POSITIONS,
        hitboxSize = DEFAULT_HITBOX_SIZE,
        padding = DEFAULT_PADDING,
        persistKey,
    } = options

    const [element, setElement] = useState<HTMLElement | null>(null)
    const [windowSize, setWindowSize] = useState({ width: window.innerWidth, height: window.innerHeight })
    const [isDragging, setIsDragging] = useState(false)
    const cleanupRef = useRef<(() => void) | null>(null)

    // State: either snapped to a fixed position, or freely dragged
    const [fixedPosition, setFixedPosition] = useState<SnapPosition | null>(() => {
        if (persistKey) {
            const persisted = loadPersistedState(persistKey)
            if (persisted) {
                return persisted.fixedPosition
            }
        }
        return defaultPosition
    })

    const [dragPosition, setDragPosition] = useState<{ x: number; y: number } | null>(() => {
        if (persistKey) {
            const persisted = loadPersistedState(persistKey)
            if (persisted) {
                return persisted.dragPosition
            }
        }
        return null
    })

    // Update window size on resize
    useEffect(() => {
        const handleResize = (): void => {
            setWindowSize({ width: window.innerWidth, height: window.innerHeight })
        }
        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    }, [])

    // Persist state changes
    useEffect(() => {
        if (persistKey) {
            persistState(persistKey, { fixedPosition, dragPosition })
        }
    }, [persistKey, fixedPosition, dragPosition])

    const snapZones = useMemo(
        () => getSnapZones(windowSize.width, windowSize.height),
        [windowSize.width, windowSize.height]
    )

    // Calculate effective position based on fixed position or drag position
    const position = useMemo(() => {
        const width = element?.offsetWidth ?? 300
        const height = element?.offsetHeight ?? 100
        const xPadding = width * 0.5 + padding
        const yPadding = height * 0.5 + padding

        // Use drag position if available, otherwise use fixed position
        const basePos = dragPosition ?? (fixedPosition ? snapZones[fixedPosition] : snapZones[defaultPosition])

        return {
            x: inBounds(xPadding, basePos.x, windowSize.width - xPadding),
            y: inBounds(yPadding, basePos.y, windowSize.height - yPadding),
        }
    }, [dragPosition, fixedPosition, snapZones, element, windowSize, padding, defaultPosition])

    const handleDragStart = useCallback(
        (clientX: number, clientY: number) => {
            if (!element) {
                return
            }

            const offsetX = clientX - position.x
            const offsetY = clientY - position.y
            const elementWidth = element.offsetWidth
            const elementHeight = element.offsetHeight
            let moveCount = 0

            const onMove = (moveX: number, moveY: number): void => {
                moveCount += 1

                if (moveCount > DRAG_THRESHOLD) {
                    setIsDragging(true)

                    // Calculate where the element would be positioned
                    const elementCenterX = moveX - offsetX
                    const elementCenterY = moveY - offsetY
                    const halfWidth = elementWidth / 2
                    const halfHeight = elementHeight / 2
                    const halfHitbox = hitboxSize / 2

                    // Check if element bounding box overlaps any snap zone hitbox
                    let closestPosition: SnapPosition | null = null
                    for (const snapPosition of allowedPositions) {
                        const snapPoint = snapZones[snapPosition]

                        // Check rectangle overlap between element and snap zone
                        const overlapsX =
                            elementCenterX - halfWidth < snapPoint.x + halfHitbox &&
                            elementCenterX + halfWidth > snapPoint.x - halfHitbox
                        const overlapsY =
                            elementCenterY - halfHeight < snapPoint.y + halfHitbox &&
                            elementCenterY + halfHeight > snapPoint.y - halfHitbox

                        if (overlapsX && overlapsY) {
                            closestPosition = snapPosition
                            break
                        }
                    }

                    if (closestPosition) {
                        setFixedPosition(closestPosition)
                        setDragPosition(null)
                    } else {
                        setFixedPosition(null)
                        setDragPosition({ x: elementCenterX, y: elementCenterY })
                    }
                }
            }

            const onMouseMove = (e: MouseEvent): void => onMove(e.clientX, e.clientY)
            const onTouchMove = (e: TouchEvent): void => onMove(e.touches[0].clientX, e.touches[0].clientY)

            const cleanup = (): void => {
                setIsDragging(false)
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onEnd)
                document.removeEventListener('touchmove', onTouchMove)
                document.removeEventListener('touchend', onEnd)
                cleanupRef.current = null
            }

            const onEnd = (): void => {
                cleanup()
            }

            // Store cleanup for unmount
            cleanupRef.current = cleanup

            document.addEventListener('mousemove', onMouseMove)
            document.addEventListener('mouseup', onEnd)
            document.addEventListener('touchmove', onTouchMove)
            document.addEventListener('touchend', onEnd)
        },
        [element, position, allowedPositions, snapZones, hitboxSize]
    )

    useEffect(() => {
        return () => {
            cleanupRef.current?.()
        }
    }, [])

    const handlers = useMemo(
        () => ({
            onMouseDown: (e: React.MouseEvent): void => {
                if (e.button === 0) {
                    handleDragStart(e.clientX, e.clientY)
                }
            },
            onTouchStart: (e: React.TouchEvent): void => {
                handleDragStart(e.touches[0].clientX, e.touches[0].clientY)
            },
        }),
        [handleDragStart]
    )

    return {
        position,
        isDragging,
        fixedPosition,
        handlers,
        snapZones,
        setElement,
    }
}
