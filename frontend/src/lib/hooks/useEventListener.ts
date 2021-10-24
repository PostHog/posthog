import { DependencyList, useEffect, useRef } from 'react'

export type KeyboardEventHandler = (event: KeyboardEvent) => void
export type EventHandler = (event: Event) => void

export function useEventListener(
    eventName: 'keyup' | 'keydown',
    handler: KeyboardEventHandler,
    element?: Element | Window,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: string,
    handler: EventHandler,
    element?: Element | Window,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: string,
    handler: EventHandler | KeyboardEventHandler,
    element: Element | Window = window,
    deps?: DependencyList
): void {
    // Create a ref that stores handler
    const savedHandler = useRef<EventHandler>(() => {})

    // This allows our effect below to always get latest handler without us needing to pass it in effect deps array,
    // which would potentially cause effect to re-run every render
    useEffect(() => {
        savedHandler.current = handler as EventHandler
    }, [handler])

    useEffect(
        () => {
            // Make sure element supports addEventListener
            if (!element?.addEventListener) {
                console.warn(
                    `Could not start listening to ${eventName} on ${(element as Element)?.localName ?? 'window'}!`
                )
                return
            }
            // Create event listener that calls handler function stored in ref
            const eventListener: EventHandler = (event) => savedHandler.current(event)
            // Add event listener
            element.addEventListener(eventName, eventListener)
            // Remove event listener on cleanup
            return () => {
                element?.removeEventListener(eventName, eventListener)
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [eventName, element, ...(deps || [])] // Re-run if eventName or element changes
    )
}
