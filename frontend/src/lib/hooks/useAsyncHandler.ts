import { useState } from 'react'

/**
 * Wraps an event handler to set a loading state while the handler is running.
 * @param onEvent The event handler to wrap.
 * @returns The wrapped event handler and a loading state.
 * @example
 * const { loading, onEvent } = useAsyncHandler(() => await api.doSomething())
 * return <LemonButton onClick={onEvent} loading={loading}>Click me</button>
 */
export function useAsyncHandler<E extends React.UIEvent>(
    onEvent: ((e: E) => any) | undefined
): { loading: boolean; onEvent: ((e: E) => void) | undefined } {
    const [loading, setLoading] = useState(false)

    const onEventWrapper = onEvent
        ? (e: E) => {
              if (onEvent) {
                  const result = onEvent(e)
                  if (result instanceof Promise) {
                      setLoading(true)
                      void result.finally(() => setLoading(false))
                  }
              }
          }
        : undefined

    return {
        loading: loading,
        onEvent: onEventWrapper,
    }
}
