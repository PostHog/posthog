import { useEffect, useState } from 'react'

export const useMousePosition = (): { x: number; y: number } => {
    const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

    useEffect(() => {
        const onMove = (e: MouseEvent): void => {
            if (e.clientX !== mousePosition.x || e.clientY !== mousePosition.y) {
                setMousePosition({ x: e.clientX, y: e.clientY })
            }
        }

        window.addEventListener('mousemove', onMove, { passive: true })
        return () => {
            window.removeEventListener('mousemove', onMove)
        }
    }, [])
    return mousePosition
}
