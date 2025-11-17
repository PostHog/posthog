import { ReferenceType } from '@floating-ui/react'
import { useEffect } from 'react'

export const CLICK_OUTSIDE_BLOCK_CLASS = 'click-outside-block'

const exceptions = [`.${CLICK_OUTSIDE_BLOCK_CLASS}`, `.${CLICK_OUTSIDE_BLOCK_CLASS} *`]

export function useOutsideClickHandler(
    refs: React.MutableRefObject<HTMLElement | ReferenceType | null>[],
    handleClickOutside: (event: Event) => void,
    extraDeps: any[] = [],
    exceptTagNames?: string[] // list of tag names that don't trigger the callback even if outside
): void {
    useEffect(() => {
        function handleClick(event: Event): void {
            if (exceptions.some((exception) => (event.target as Element)?.matches?.(exception))) {
                return
            }
            if (
                refs.some((maybeRef) => {
                    if (typeof maybeRef === 'string') {
                        return event.composedPath?.()?.find((e) => (e as HTMLElement)?.matches?.(maybeRef))
                    }
                    const ref = maybeRef.current

                    if (!event.target || !ref) {
                        return false
                    }

                    const hasShadowRoot = !!(event.target as HTMLElement).shadowRoot
                    return hasShadowRoot
                        ? event.composedPath?.()?.find((el) => el === ref)
                        : `contains` in ref && ref.contains(event.target as Element)
                })
            ) {
                return
            }
            const target = (event.composedPath?.()?.[0] || event.target) as HTMLElement
            if (exceptTagNames && exceptTagNames.includes(target.tagName)) {
                return
            }
            handleClickOutside?.(event)
        }

        // Only attach event listeners if there's something to track
        if (refs.length > 0) {
            document.addEventListener('mouseup', handleClick)
            document.addEventListener('touchend', handleClick)
            return () => {
                document.removeEventListener('mouseup', handleClick)
                document.removeEventListener('touchend', handleClick)
            }
        }
    }, [...refs, ...extraDeps]) // oxlint-disable-line react-hooks/exhaustive-deps
}
