import { useCallback, useEffect, useRef } from 'react'

export interface HoverIntentHandlers {
    start: () => void
    cancel: () => void
}

export function useHoverIntent(onIntent: (() => void) | undefined, delayMs: number): HoverIntentHandlers {
    const timer = useRef<number | null>(null)
    const callback = useRef(onIntent)
    callback.current = onIntent

    const cancel = useCallback((): void => {
        if (timer.current !== null) {
            window.clearTimeout(timer.current)
            timer.current = null
        }
    }, [])
    const start = useCallback((): void => {
        cancel()
        if (!callback.current) {
            return
        }
        timer.current = window.setTimeout(() => {
            timer.current = null
            callback.current?.()
        }, delayMs)
    }, [cancel, delayMs])

    useEffect(() => cancel, [cancel])
    return { start, cancel }
}
