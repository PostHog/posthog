import { useEffect, useState } from 'react'

/**
 * Hook to get the current mouse position relative to the window.
 * Optionally takes a container element.
 * if one is provided, the position will be relative to the container.
 */
export const useMousePosition = (container?: HTMLElement | null): { x: number; y: number } => {
    const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

    useEffect(() => {
        const onMove = (e: MouseEvent): void => {
            const rect = container ? container.getBoundingClientRect() : { left: 0, top: 0 }
            const newX = e.clientX - rect.left
            const newY = e.clientY - rect.top
            const inBounds = newX >= 0 && newY >= 0

            setMousePosition((prev) => {
                const hasChanged = newX !== prev.x || newY !== prev.y
                return inBounds && hasChanged ? { x: newX, y: newY } : prev
            })
        }

        window.addEventListener('mousemove', onMove, { passive: true })
        return () => {
            window.removeEventListener('mousemove', onMove)
        }
    }, [container])

    return mousePosition
}
