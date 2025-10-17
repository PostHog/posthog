import { DependencyList, useEffect, useRef } from 'react'

export type KeyboardEventHandler = (event: KeyboardEvent) => void
export type TouchEventHandler = (event: TouchEvent) => void
export type MouseEventHandler = (event: MouseEvent) => void
export type EventHandler = (event: Event) => void

export function useEventListener(
    eventName: `key${string}`,
    handler: KeyboardEventHandler,
    element?: Element | Window | null,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: `touch${string}`,
    handler: TouchEventHandler,
    element?: Element | Window | null,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: `mouse${string}`,
    handler: MouseEventHandler,
    element?: Element | Window | null,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: string,
    handler: EventHandler,
    element?: Element | Window | null,
    deps?: DependencyList
): void
export function useEventListener(
    eventName: string,
    handler: KeyboardEventHandler | TouchEventHandler | MouseEventHandler | EventHandler,
    element: Element | Window | null = window,
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
                    `Could not start listening to ${eventName} on ${
                        !element ? element : ((element as Element)?.localName ?? 'window')
                    }!`
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

        [eventName, element, ...(deps || [])] // Re-run if eventName or element changes
    )
}
