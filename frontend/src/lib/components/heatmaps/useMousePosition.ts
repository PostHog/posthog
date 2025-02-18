import { useEffect, useState } from 'react'

export const useMousePosition = (): { x: number; y: number } => {
    const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

    useEffect(() => {
        const onMove = (e: MouseEvent): void => {
            setMousePosition({ x: e.clientX, y: e.clientY })
        }

        window.addEventListener('mousemove', onMove)
        return () => {
            window.removeEventListener('mousemove', onMove)
        }
    }, [])
    return mousePosition
}
