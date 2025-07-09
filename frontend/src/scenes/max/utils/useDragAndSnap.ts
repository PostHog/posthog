import { useEffect, useRef, useState } from 'react'
import {
    calculateSnapPosition,
    getFloatingMaxDimensions,
    getElementDimensions,
    Position,
    PositionWithSide,
} from './floatingMaxPositioning'

const DRAG_THRESHOLD = 5 // pixels
const SNAP_THRESHOLD = 100 // pixels - threshold for snapping to opposite side
const ANIMATION_DURATION = 300 // milliseconds
const CACHED_BOTTOM_OFFSET_DEFAULT = 6 // pixels
const MIN_SCREEN_WIDTH_FOR_DRAG = 640 // sm breakpoint in pixels

interface UseDragAndSnapProps {
    onPositionChange?: (position: PositionWithSide) => void
    disabled?: boolean
    currentSide?: 'left' | 'right'
    dragElementRef?: React.RefObject<HTMLDivElement>
    containerRef?: React.RefObject<HTMLElement>
}

interface UseDragAndSnapReturn {
    isDragging: boolean
    isAnimating: boolean
    hasDragged: boolean
    containerStyle: React.CSSProperties
    handleMouseDown: (e: React.MouseEvent) => void
    dragElementRef: React.RefObject<HTMLDivElement>
}

type MousePosition = Position

/**
 * Custom hook for drag and snap behavior of floating Max AI avatar
 * Handles mouse interactions, drag detection, and snapping to panel sides
 */
export function useDragAndSnap({
    onPositionChange,
    disabled = false,
    currentSide,
    dragElementRef: externalDragElementRef,
    containerRef: externalContainerRef,
}: UseDragAndSnapProps): UseDragAndSnapReturn {
    const [isDragging, setIsDragging] = useState(false)
    const [dragOffset, setDragOffset] = useState<Position>({ x: 0, y: 0 })
    const [hasDragged, setHasDragged] = useState(false)
    const [dragPosition, setDragPosition] = useState<Position | null>(null)
    const [isAnimating, setIsAnimating] = useState(false)
    const [mouseDownPosition, setMouseDownPosition] = useState<MousePosition | null>(null)
    const [cachedBottomOffset, setCachedBottomOffset] = useState<number>(CACHED_BOTTOM_OFFSET_DEFAULT)
    const internalDragElementRef = useRef<HTMLDivElement>(null)
    const internalContainerRef = useRef<HTMLDivElement>(null)
    const dragElementRef = externalDragElementRef || internalDragElementRef
    const containerRef = externalContainerRef || internalContainerRef

    // Cache the bottom offset when not dragging
    useEffect(() => {
        if (!isDragging && !isAnimating) {
            const floatingMaxContainer =
                containerRef.current || (document.querySelector('[data-attr="floating-max-container"]') as HTMLElement)
            if (floatingMaxContainer) {
                const computedStyle = getComputedStyle(floatingMaxContainer)
                const borderBottomWidth = parseFloat(computedStyle.borderBottomWidth) || 0
                const bottomOffset = 8 + borderBottomWidth // 8px for mb-2
                setCachedBottomOffset(bottomOffset)
            }
        }
    }, [isDragging, isAnimating, containerRef])

    // Handle drag functionality
    useEffect(() => {
        const handleMouseMove = (e: MouseEvent): void => {
            if (!mouseDownPosition) {
                return
            }

            const deltaX = Math.abs(e.clientX - mouseDownPosition.x)
            const deltaY = Math.abs(e.clientY - mouseDownPosition.y)

            // Only start dragging if mouse moved beyond threshold
            if (!isDragging && (deltaX > DRAG_THRESHOLD || deltaY > DRAG_THRESHOLD)) {
                setIsDragging(true)
                setHasDragged(true)
            }

            if (isDragging) {
                const newPosition: Position = {
                    x: e.clientX - dragOffset.x,
                    y: e.clientY - dragOffset.y,
                }
                setDragPosition(newPosition)
            }
        }

        const handleMouseUp = (e: MouseEvent): void => {
            if (e.button !== 0) {
                return
            }

            setMouseDownPosition(null)

            if (!isDragging) {
                return
            }

            setIsDragging(false)

            // Only snap if the user actually dragged
            if (hasDragged) {
                setIsAnimating(true)

                const containerElement = containerRef?.current
                const { width: elementWidth, height: elementHeight } = containerElement
                    ? getElementDimensions(containerElement)
                    : dragElementRef.current
                    ? getElementDimensions(dragElementRef.current)
                    : getFloatingMaxDimensions()
                const snapPosition = calculateSnapPosition(
                    e.clientX,
                    cachedBottomOffset,
                    elementWidth,
                    mouseDownPosition?.x,
                    currentSide,
                    SNAP_THRESHOLD,
                    elementHeight
                )

                // Animate to final position
                setDragPosition({ x: snapPosition.x, y: snapPosition.y })

                // After animation completes, reset everything and notify parent
                setTimeout(() => {
                    setDragPosition(null)
                    setIsAnimating(false)
                    setHasDragged(false)

                    // Notify parent of position change
                    onPositionChange?.(snapPosition)
                }, ANIMATION_DURATION)
            } else {
                setDragPosition(null)
                setHasDragged(false)
            }
        }

        if (mouseDownPosition) {
            document.addEventListener('mousemove', handleMouseMove)
            document.addEventListener('mouseup', handleMouseUp)
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove)
            document.removeEventListener('mouseup', handleMouseUp)
        }
    }, [isDragging, dragOffset, onPositionChange, hasDragged, mouseDownPosition, cachedBottomOffset])

    const handleMouseDown = (e: React.MouseEvent): void => {
        if (disabled || e.button !== 0) {
            return
        }

        // Disable drag on touch devices or very small screens
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
        const isVerySmallScreen = window.innerWidth < MIN_SCREEN_WIDTH_FOR_DRAG

        if ((isTouchDevice && isVerySmallScreen) || !dragElementRef.current) {
            return
        }

        const dragElementRect = dragElementRef.current.getBoundingClientRect()
        const containerElement = containerRef?.current || dragElementRef.current
        const containerRect = containerElement.getBoundingClientRect()

        // Calculate offset relative to the container, but based on where the user clicked on the drag element
        const dragOffsetX = e.clientX - dragElementRect.left
        const dragOffsetY = e.clientY - dragElementRect.top

        // Calculate the offset from the drag element to the container
        const elementToContainerOffsetX = dragElementRect.left - containerRect.left
        const elementToContainerOffsetY = dragElementRect.top - containerRect.top

        setDragOffset({
            x: dragOffsetX + elementToContainerOffsetX,
            y: dragOffsetY + elementToContainerOffsetY,
        })
        setMouseDownPosition({ x: e.clientX, y: e.clientY })
        setDragPosition({ x: containerRect.left, y: containerRect.top })
        e.preventDefault()
    }

    const containerStyle: React.CSSProperties =
        (isDragging || isAnimating) && dragPosition
            ? {
                  position: 'fixed',
                  left: dragPosition.x,
                  top: dragPosition.y,
                  zIndex: 1000,
                  pointerEvents: isDragging ? 'none' : 'auto',
                  transition: isAnimating ? 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)' : 'none',
              }
            : {}

    return {
        isDragging,
        isAnimating,
        hasDragged,
        containerStyle,
        handleMouseDown,
        dragElementRef,
    }
}
