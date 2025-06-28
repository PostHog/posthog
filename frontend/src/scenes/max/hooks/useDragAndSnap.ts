import { getCSSVariableValue } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

// Constants
const DRAG_THRESHOLD = 5 // pixels
const ANIMATION_DURATION = 300 // milliseconds
const PANEL_FIXED_DISTANCE = 4 // pixels from panel edge
const CACHED_BOTTOM_OFFSET_DEFAULT = 6 // pixels
const MIN_SCREEN_WIDTH_FOR_DRAG = 640 // sm breakpoint in pixels

interface UseDragAndSnapProps {
    onPositionChange?: (position: { x: number; y: number; side: 'left' | 'right' }) => void
    disabled?: boolean
}

interface DragPosition {
    x: number
    y: number
}

type MousePosition = DragPosition

/**
 * Calculate the final snap position based on mouse position
 */
function calculateSnapPosition(
    mouseX: number,
    bottomOffset: number
): {
    finalPosition: DragPosition
    side: 'left' | 'right'
} {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const isRightSide = mouseX > windowWidth / 2

    const sidePanel = document.getElementById('side-panel')
    const sidePanelWidth = sidePanel?.getBoundingClientRect().width || 0
    const projectPanel = document.getElementById('project-panel-layout')
    const projectPanelWidth = projectPanel?.getBoundingClientRect().width || 0
    const xPadding = getCSSVariableValue('--scene-padding', 'Navigation3000')
    const floatingMax = document.getElementById('floating-max')
    const avatarWidth = floatingMax?.getBoundingClientRect().width || 0

    const finalX = isRightSide
        ? windowWidth - (sidePanelWidth + xPadding + PANEL_FIXED_DISTANCE + avatarWidth)
        : projectPanelWidth + xPadding + PANEL_FIXED_DISTANCE

    const finalY = windowHeight - avatarWidth - bottomOffset

    return {
        finalPosition: { x: finalX, y: finalY },
        side: isRightSide ? 'right' : 'left',
    }
}

interface UseDragAndSnapReturn {
    isDragging: boolean
    isAnimating: boolean
    hasDragged: boolean
    containerStyle: React.CSSProperties
    handleMouseDown: (e: React.MouseEvent) => void
    avatarButtonRef: React.RefObject<HTMLDivElement>
}

export function useDragAndSnap({ onPositionChange, disabled = false }: UseDragAndSnapProps): UseDragAndSnapReturn {
    const [isDragging, setIsDragging] = useState(false)
    const [dragOffset, setDragOffset] = useState<DragPosition>({ x: 0, y: 0 })
    const [hasDragged, setHasDragged] = useState(false)
    const [dragPosition, setDragPosition] = useState<DragPosition | null>(null)
    const [isAnimating, setIsAnimating] = useState(false)
    const [mouseDownPosition, setMouseDownPosition] = useState<MousePosition | null>(null)
    const [cachedBottomOffset, setCachedBottomOffset] = useState<number>(CACHED_BOTTOM_OFFSET_DEFAULT)
    const avatarButtonRef = useRef<HTMLDivElement>(null)

    // Cache the bottom offset when not dragging
    useEffect(() => {
        if (!isDragging && !isAnimating) {
            const floatingMaxContainer = document.querySelector('[data-attr="floating-max-container"]') as HTMLElement
            if (floatingMaxContainer) {
                const computedStyle = getComputedStyle(floatingMaxContainer)
                const marginBottom = parseFloat(computedStyle.marginBottom) || 0
                const paddingBottom = parseFloat(computedStyle.paddingBottom) || 0
                const borderBottomWidth = parseFloat(computedStyle.borderBottomWidth) || 0
                const bottomOffset = marginBottom + paddingBottom + borderBottomWidth
                setCachedBottomOffset(bottomOffset)
            }
        }
    }, [isDragging, isAnimating])

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
                const newPosition: DragPosition = {
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

                const { finalPosition, side } = calculateSnapPosition(e.clientX, cachedBottomOffset)

                // Animate to final position
                setDragPosition(finalPosition)

                // After animation completes, reset everything and notify parent
                setTimeout(() => {
                    setDragPosition(null)
                    setIsAnimating(false)
                    setHasDragged(false)

                    // Notify parent of position change
                    if (onPositionChange) {
                        onPositionChange({
                            x: finalPosition.x,
                            y: finalPosition.y,
                            side,
                        })
                    }
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
    }, [isDragging, dragOffset, onPositionChange, hasDragged, mouseDownPosition])

    const handleMouseDown = (e: React.MouseEvent): void => {
        if (disabled || e.button !== 0) {
            return
        }

        // Disable drag on touch devices or very small screens
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
        const isVerySmallScreen = window.innerWidth < MIN_SCREEN_WIDTH_FOR_DRAG

        if ((isTouchDevice && isVerySmallScreen) || !avatarButtonRef.current) {
            return
        }

        const rect = avatarButtonRef.current.getBoundingClientRect()
        setDragOffset({
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
        })
        setMouseDownPosition({ x: e.clientX, y: e.clientY })
        setDragPosition({ x: rect.left, y: rect.top })
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
        avatarButtonRef,
    }
}
