import { useEffect, useRef } from 'react'

import { usePageVisibility } from './usePageVisibility'

export function useInterval(callback: () => void, delay: number | null): void {
    const savedCallback = useRef(callback)

    useEffect(() => {
        savedCallback.current = callback
    }, [callback])
    const { isVisible } = usePageVisibility()

    useEffect(() => {
        if (delay === null || !isVisible) {
            return
        }

        const id = setInterval(() => savedCallback.current(), delay)
        return () => clearInterval(id)
    }, [delay, isVisible])
}
