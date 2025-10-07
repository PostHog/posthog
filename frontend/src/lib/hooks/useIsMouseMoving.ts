import { useEffect, useRef, useState } from 'react'

export const useIsMouseMoving = (
    ref: React.RefObject<HTMLElement>,
    timeAfterWhichToConsiderStopped: number
): boolean => {
    const [isMoving, setIsMoving] = useState(false)
    const timeoutRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
        const handleMouseMove = (): void => {
            setIsMoving(true)
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
            timeoutRef.current = setTimeout(() => {
                setIsMoving(false)
            }, timeAfterWhichToConsiderStopped)
        }

        const current = ref.current
        if (current) {
            current.addEventListener('mousemove', handleMouseMove)
        }

        return () => {
            if (current) {
                current.removeEventListener('mousemove', handleMouseMove)
            }
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [ref, timeAfterWhichToConsiderStopped])

    return isMoving
}
