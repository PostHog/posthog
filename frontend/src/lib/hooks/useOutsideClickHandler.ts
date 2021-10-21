import { useEffect } from 'react'

const exceptions = ['.ant-select-dropdown *', '.click-outside-block', '.click-outside-block *']

export function useOutsideClickHandler(
    refOrRefs: Element | null | (Element | null)[],
    handleClickOutside?: (event: Event) => void,
    extraDeps: any[] = []
): void {
    const allRefs = (Array.isArray(refOrRefs) ? refOrRefs : [refOrRefs]).map((f) => f)

    useEffect(
        () => {
            function handleClick(event: Event): void {
                if (exceptions.some((exception) => (event.target as Element).matches(exception))) {
                    return
                }
                if (allRefs.some((ref) => ref?.contains(event.target as Element))) {
                    return
                }
                handleClickOutside?.(event)
            }

            if (allRefs.length > 0) {
                // only attach event listeners if there's something to track
                document.addEventListener('mousedown', handleClick)
                return () => document.removeEventListener('mousedown', handleClick)
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [...allRefs, ...extraDeps]
    )
}
