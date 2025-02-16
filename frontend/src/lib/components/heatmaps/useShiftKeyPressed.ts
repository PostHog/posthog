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

        window.addEventListener('keydown', handleKeyDown)
        window.addEventListener('keyup', handleKeyUp)

        return () => {
            window.removeEventListener('keydown', handleKeyDown)
            window.removeEventListener('keyup', handleKeyUp)
        }
    }, [])

    return isShiftPressed
}
