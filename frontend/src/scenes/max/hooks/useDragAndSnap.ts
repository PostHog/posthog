import { useEffect, useRef, useState } from 'react'

interface UseDragAndSnapProps {
    onPositionChange?: (position: { x: number; y: number; side: 'left' | 'right' }) => void
    disabled?: boolean
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
    const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
    const [hasDragged, setHasDragged] = useState(false)
    const [dragPosition, setDragPosition] = useState<{ x: number; y: number } | null>(null)
    const [isAnimating, setIsAnimating] = useState(false)
    const [mouseDownPosition, setMouseDownPosition] = useState<{ x: number; y: number } | null>(null)
    const avatarButtonRef = useRef<HTMLDivElement>(null)

    // Handle drag functionality
    useEffect(() => {
        const handleMouseMove = (e: MouseEvent): void => {
            if (!mouseDownPosition) {
                return
            }

            const dragThreshold = 5 // pixels
            const deltaX = Math.abs(e.clientX - mouseDownPosition.x)
            const deltaY = Math.abs(e.clientY - mouseDownPosition.y)

            // Only start dragging if mouse moved beyond threshold
            if (!isDragging && (deltaX > dragThreshold || deltaY > dragThreshold)) {
                setIsDragging(true)
                setHasDragged(true)
            }

            if (isDragging) {
                const newX = e.clientX - dragOffset.x
                const newY = e.clientY - dragOffset.y
                setDragPosition({ x: newX, y: newY })
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
                // Determine which side to snap to based on mouse position
                const windowWidth = window.innerWidth
                const windowHeight = window.innerHeight
                const isRightSide = e.clientX > windowWidth / 2

                // Calculate the final position to match CSS positioning
                // The container has w-80 (320px) and positioning classes
                // For right side: right-[calc(1rem-1px)] md:right-[calc(3rem-1px)]
                // For left side: left-[calc(1rem-1px)] md:left-[calc(3rem-1px)]
                const isDesktop = windowWidth >= 768 // md breakpoint
                const containerWidth = 320 // w-80
                const cssRightOffset = isDesktop ? 48 - 1 : 16 - 1 // 3rem-1px : 1rem-1px
                const cssLeftOffset = isDesktop ? 48 - 1 : 16 - 1 // 3rem-1px : 1rem-1px

                // The avatar is positioned within the container with mr-4 (16px) from right edge
                // and the avatar itself is 44px wide
                let finalX: number
                if (isRightSide) {
                    // For right side: windowWidth - cssRightOffset - containerWidth + (containerWidth - 16 - 46)
                    finalX = windowWidth - cssRightOffset - 16 - 44 // Direct positioning from right edge
                } else {
                    // For left side: cssLeftOffset + (containerWidth - 16 - 46)
                    finalX = cssLeftOffset + containerWidth - 16 - 32 - 44 // Position accounting for container layout
                }

                const finalY = windowHeight - 16 - 44 + 8 // bottom offset - avatar height - mb-2

                // Animate to final position
                setDragPosition({ x: finalX, y: finalY })

                // After animation completes, reset everything and notify parent
                setTimeout(() => {
                    setDragPosition(null)
                    setIsAnimating(false)
                    setHasDragged(false)

                    // Notify parent of position change
                    if (onPositionChange) {
                        onPositionChange({
                            x: finalX,
                            y: finalY,
                            side: isRightSide ? 'right' : 'left',
                        })
                    }
                }, 300) // Match transition duration
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
        const isVerySmallScreen = window.innerWidth < 640 // sm breakpoint

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
