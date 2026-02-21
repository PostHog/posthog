import { useCallback, useEffect, useRef, useState } from 'react'

interface UseDelayedHoverOptions {
    showDelay?: number
    hideDelay?: number
}

interface UseDelayedHoverResult {
    visible: boolean
    show: () => void
    hide: () => void
}

export function useDelayedHover({
    showDelay = 500,
    hideDelay = 200,
}: UseDelayedHoverOptions = {}): UseDelayedHoverResult {
    const [visible, setVisible] = useState(false)
    const showRef = useRef<ReturnType<typeof setTimeout>>()
    const hideRef = useRef<ReturnType<typeof setTimeout>>()

    useEffect(() => {
        return () => {
            clearTimeout(showRef.current)
            clearTimeout(hideRef.current)
        }
    }, [])

    const show = useCallback(() => {
        clearTimeout(hideRef.current)
        showRef.current = setTimeout(() => setVisible(true), showDelay)
    }, [showDelay])

    const hide = useCallback(() => {
        clearTimeout(showRef.current)
        hideRef.current = setTimeout(() => setVisible(false), hideDelay)
    }, [hideDelay])

    return { visible, show, hide }
}
