import { useCallback, useRef, useState } from 'react'

/**
 * Wraps an event handler to set a loading state while the handler is running.
 * Returns a stable function reference via ref pattern to avoid unnecessary re-renders.
 *
 * @example
 * const { loading, onEvent } = useAsyncHandler(() => await api.doSomething())
 * return <LemonButton onClick={onEvent} loading={loading}>Click me</LemonButton>
 */
export function useAsyncHandler<E extends React.UIEvent>(
    onEvent: ((e: E) => any) | undefined
): { loading: boolean; onEvent: ((e: E) => void) | undefined } {
    const [loading, setLoading] = useState(false)
    const onEventRef = useRef(onEvent)
    onEventRef.current = onEvent

    const stableWrapper = useCallback((e: E) => {
        const handler = onEventRef.current
        if (handler) {
            const result = handler(e)
            if (result instanceof Promise) {
                setLoading(true)
                void result.finally(() => setLoading(false))
            }
        }
    }, [])

    return {
        loading,
        onEvent: onEvent ? stableWrapper : undefined,
    }
}
