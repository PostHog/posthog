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

    // Tracks whether the most recent down event landed inside any tracked ref, so a release
    // outside (e.g. a scrollbar drag) isn't mistaken for an outside click. A single flag is
    // enough: gestures are processed one at a time, and the rare overlapping multi-touch case
    // degrades gracefully (the last touch's start position wins).
    const gestureStartedInsideRef = useRef(false)

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
            gestureStartedInsideRef.current = isInsideRefs(event)
        }

        function handleClick(event: Event): void {
            const startedInside = gestureStartedInsideRef.current
            gestureStartedInsideRef.current = false

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
