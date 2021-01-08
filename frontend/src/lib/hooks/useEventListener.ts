import { useEffect, useRef } from 'react'

export type EventHandler = (event: Event) => void

export function useEventListener(eventName: string, handler: EventHandler, element: Element | Window = window): void {
    // Create a ref that stores handler
    const savedHandler = useRef<EventHandler>(() => {})

    // This allows our effect below to always get latest handler without us needing to pass it in effect deps array,
    // which would potentially cause effect to re-run every render
    useEffect(() => {
        savedHandler.current = handler
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
                element.removeEventListener(eventName, eventListener)
            }
        },
        [eventName, element] // Re-run if eventName or element changes
    )
}
