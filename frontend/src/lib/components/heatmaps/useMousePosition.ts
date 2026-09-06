import { useEffect, useState } from 'react'

export type MousePosition = { x: number; y: number }

function positionIn(e: MouseEvent, container?: HTMLElement | null): MousePosition | null {
    if (!container) {
        return { x: e.clientX, y: e.clientY }
    }
    const rect = container.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    return x >= 0 && y >= 0 && x <= rect.width && y <= rect.height ? { x, y } : null
}

/**
 * Hook to get the current mouse position relative to the window.
 * Optionally takes a container element.
 * if one is provided, the position will be relative to the container.
 */
export function useMousePosition(container?: HTMLElement | null): MousePosition | null {
    const [mousePosition, setMousePosition] = useState<MousePosition | null>(null)

    useEffect(() => {
        const onMove = (e: MouseEvent): void => {
            setMousePosition(positionIn(e, container))
        }

        window.addEventListener('mousemove', onMove, { passive: true })
        return () => {
            window.removeEventListener('mousemove', onMove)
        }
    }, [container])

    return mousePosition
}
