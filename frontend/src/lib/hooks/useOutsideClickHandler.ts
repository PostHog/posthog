import { useEffect } from 'react'

const exceptions = ['.ant-select-dropdown *', '.click-outside-block', '.click-outside-block *']

export function useOutsideClickHandler(
    refOrRefs: string | React.MutableRefObject<any> | (React.MutableRefObject<any> | string)[],
    handleClickOutside?: (event: Event) => void,
    extraDeps: any[] = [],
    exceptTagNames?: string[] // list of tag names that don't trigger the callback even if outside
): void {
    const allRefs = Array.isArray(refOrRefs) ? refOrRefs : [refOrRefs]

    useEffect(() => {
        function handleClick(event: Event): void {
            if (exceptions.some((exception) => (event.target as Element).matches(exception))) {
                return
            }
            if (
                allRefs.some((maybeRef) => {
                    if (typeof maybeRef === 'string') {
                        return event.composedPath?.()?.find((e) => (e as HTMLElement)?.matches?.(maybeRef))
                    } else {
                        const ref = maybeRef.current
                        return event.target && ref && `contains` in ref && ref.contains(event.target as Element)
                    }
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

        if (allRefs.length > 0) {
            // Only attach event listeners if there's something to track
            document.addEventListener('mouseup', handleClick)
            document.addEventListener('touchend', handleClick)
            return () => {
                document.removeEventListener('mouseup', handleClick)
                document.removeEventListener('touchend', handleClick)
            }
        }
    }, [...allRefs, ...extraDeps])
}
