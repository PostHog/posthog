import { useEffect, useState } from 'react'

export function useShiftKeyPressed(): boolean {
    const [isShiftPressed, setIsShiftPressed] = useState(false)

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Shift') {
                setIsShiftPressed(true)
            }
        }

        const handleKeyUp = (event: KeyboardEvent): void => {
            if (event.key === 'Shift') {
                setIsShiftPressed(false)
            }
        }

        window.addEventListener('keydown', handleKeyDown, { passive: true })
        window.addEventListener('keyup', handleKeyUp, { passive: true })

        return () => {
            window.removeEventListener('keydown', handleKeyDown)
            window.removeEventListener('keyup', handleKeyUp)
        }
    }, [])

    return isShiftPressed
}
