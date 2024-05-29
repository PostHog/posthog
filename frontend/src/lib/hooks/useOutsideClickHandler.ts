import { ReferenceType } from '@floating-ui/react'
import { useEffect } from 'react'

import { useFloatingContainer } from './useFloatingContainerContext'

export const CLICK_OUTSIDE_BLOCK_CLASS = 'click-outside-block'

const exceptions = ['.ant-select-dropdown *', `.${CLICK_OUTSIDE_BLOCK_CLASS}`, `.${CLICK_OUTSIDE_BLOCK_CLASS} *`]

export function useOutsideClickHandler(
    refs: React.MutableRefObject<HTMLElement | ReferenceType | null>[],
    handleClickOutside: (event: Event) => void,
    extraDeps: any[] = [],
    exceptTagNames?: string[] // list of tag names that don't trigger the callback even if outside
): void {
    const floatingContainer = useFloatingContainer()

    useEffect(() => {
        function handleClick(event: Event): void {
            if (exceptions.some((exception) => (event.target as Element)?.matches(exception))) {
                return
            }
            if (
                refs.some((maybeRef) => {
                    if (typeof maybeRef === 'string') {
                        return event.composedPath?.()?.find((e) => (e as HTMLElement)?.matches?.(maybeRef))
                    }
                    const ref = maybeRef.current
                    return event.target && ref && `contains` in ref && ref.contains(event.target as Element)
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

        if (refs.length > 0) {
            // Only attach event listeners if there's something to track
            const root = floatingContainer || document

            root.addEventListener('mouseup', handleClick)
            root.addEventListener('touchend', handleClick)
            return () => {
                root.removeEventListener('mouseup', handleClick)
                root.removeEventListener('touchend', handleClick)
            }
        }
    }, [...refs, ...extraDeps])
}
