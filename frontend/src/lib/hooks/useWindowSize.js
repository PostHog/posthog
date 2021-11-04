import { useState, useEffect } from 'react'

export function useWindowSize() {
    const isClient = typeof window === 'object'

    function getSize() {
        return {
            width: isClient ? window.innerWidth : undefined,
            height: isClient ? window.innerHeight : undefined,
        }
    }

    const [windowSize, setWindowSize] = useState(getSize)

    useEffect(
        () => {
            if (!isClient) {
                return false
            }

            function handleResize() {
                setWindowSize(getSize())
            }

            window.addEventListener('resize', handleResize)
            return () => window.removeEventListener('resize', handleResize)
        },

        [] // Empty array ensures that effect is only run on mount and unmount
    )

    return windowSize
}
