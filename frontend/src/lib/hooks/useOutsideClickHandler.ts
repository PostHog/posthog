import { ReferenceType } from '@floating-ui/react'
import { useEffect, useRef } from 'react'

export const CLICK_OUTSIDE_BLOCK_CLASS = 'click-outside-block'

const exceptions = [`.${CLICK_OUTSIDE_BLOCK_CLASS}`, `.${CLICK_OUTSIDE_BLOCK_CLASS} *`]

export function useOutsideClickHandler(
    refs: React.MutableRefObject<HTMLElement | ReferenceType | null>[],
    handleClickOutside: (event: Event) => void,
    extraDeps: any[] = [],
    exceptTagNames?: string[] // list of tag names that don't trigger the callback even if outside
): void {
    // Store refs and callback in mutable refs so the effect closure always
    // sees the latest values without needing them in the dependency array.
    // This avoids spreading `refs` into useEffect deps (which would change
    // the array length when refs go from [] to [ref1, ref2, ...]).
    const refsRef = useRef(refs)
    refsRef.current = refs

    const handleClickOutsideRef = useRef(handleClickOutside)
    handleClickOutsideRef.current = handleClickOutside

    const exceptTagNamesRef = useRef(exceptTagNames)
    exceptTagNamesRef.current = exceptTagNames

    // Tracks per-gesture whether the down event landed inside any tracked ref. Keyed by
    // touch identifier for `TouchEvent`s, and a separate sentinel for the mouse — touch
    // identifiers are integers starting at 0, so we can't share a key space with mouse.
    const MOUSE_GESTURE_KEY = 'mouse' as const
    const gestureStartedInsideMap = useRef<Map<number | typeof MOUSE_GESTURE_KEY, boolean>>(new Map())

    useEffect(() => {
        function isInsideRefs(event: Event): boolean {
            return refsRef.current.some((maybeRef) => {
                if (typeof maybeRef === 'string') {
                    return !!event.composedPath?.()?.find((e) => (e as HTMLElement)?.matches?.(maybeRef))
                }
                const ref = maybeRef.current

                if (!event.target || !ref) {
                    return false
                }

                const hasShadowRoot = !!(event.target as HTMLElement).shadowRoot
                return hasShadowRoot
                    ? !!event.composedPath?.()?.find((el) => el === ref)
                    : `contains` in ref && ref.contains(event.target as Element)
            })
        }

        function handleGestureStart(event: Event): void {
            if (event instanceof MouseEvent && event.button !== 0) {
                return
            }
            const inside = isInsideRefs(event)
            if (typeof TouchEvent !== 'undefined' && event instanceof TouchEvent) {
                // Track each newly-started touch independently so a concurrent touch
                // outside the popover doesn't overwrite an earlier touch that started inside.
                for (let i = 0; i < event.changedTouches.length; i++) {
                    gestureStartedInsideMap.current.set(event.changedTouches[i].identifier, inside)
                }
            } else {
                gestureStartedInsideMap.current.set(MOUSE_GESTURE_KEY, inside)
            }
        }

        function handleClick(event: Event): void {
            // Pull and clear the entries for the gesture(s) ending in this event.
            // For touchend with multiple ended touches, treat the release as "started inside"
            // if *any* ended touch began inside — matches the single-touch semantics.
            let startedInside = false
            if (typeof TouchEvent !== 'undefined' && event instanceof TouchEvent) {
                for (let i = 0; i < event.changedTouches.length; i++) {
                    const id = event.changedTouches[i].identifier
                    if (gestureStartedInsideMap.current.get(id)) {
                        startedInside = true
                    }
                    gestureStartedInsideMap.current.delete(id)
                }
            } else {
                startedInside = gestureStartedInsideMap.current.get(MOUSE_GESTURE_KEY) ?? false
                gestureStartedInsideMap.current.delete(MOUSE_GESTURE_KEY)
            }

            // Ignore non-primary clicks (right-click, middle-click).
            // Radix context menus (BrowserLikeMenuItems) fire `contextmenu` before `mouseup`,
            // causing the browser to retarget `mouseup` to <html> which falsely triggers outside-click dismissal.
            if (event instanceof MouseEvent && event.button !== 0) {
                return
            }
            // If the gesture started inside a tracked ref (e.g. scrollbar drag, text selection
            // that ends outside the popover), don't treat the release as an outside click.
            if (startedInside) {
                return
            }
            if (exceptions.some((exception) => (event.target as Element)?.matches?.(exception))) {
                return
            }
            if (isInsideRefs(event)) {
                return
            }
            const target = (event.composedPath?.()?.[0] || event.target) as HTMLElement
            if (exceptTagNamesRef.current && exceptTagNamesRef.current.includes(target.tagName)) {
                return
            }
            handleClickOutsideRef.current?.(event)
        }

        // Only attach event listeners if there's something to track
        if (refsRef.current.length > 0) {
            document.addEventListener('mousedown', handleGestureStart, true)
            document.addEventListener('touchstart', handleGestureStart, true)
            document.addEventListener('mouseup', handleClick)
            document.addEventListener('touchend', handleClick)
            return () => {
                document.removeEventListener('mousedown', handleGestureStart, true)
                document.removeEventListener('touchstart', handleGestureStart, true)
                document.removeEventListener('mouseup', handleClick)
                document.removeEventListener('touchend', handleClick)
            }
        }
    }, extraDeps) // eslint-disable-line react-hooks/exhaustive-deps
}
