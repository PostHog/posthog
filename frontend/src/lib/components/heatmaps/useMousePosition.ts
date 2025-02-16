import { useEffect, useState } from 'react'

export const useMousePosition = (container?: HTMLElement | null): { x: number; y: number } => {
    const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

    useEffect(
        () => {
            const onMove = (e: MouseEvent): void => {
                if (container) {
                    const rect = (container || window).getBoundingClientRect()
                    setMousePosition({
                        x: e.clientX - rect.left,
                        y: e.clientY - rect.top,
                    })
                } else {
                    setMousePosition({ x: e.clientX, y: e.clientY })
                }
            }

            window.addEventListener('mousemove', onMove, { passive: true })
            return () => {
                window.removeEventListener('mousemove', onMove)
            }
        },
        [
            // don't need container as a dependency because it changes the behaviour not the listener
        ]
    )

    return mousePosition
}
