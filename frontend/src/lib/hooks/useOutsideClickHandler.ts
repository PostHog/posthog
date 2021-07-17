import { useEffect } from 'react'

const exceptions = ['.ant-select-dropdown *']

export function useOutsideClickHandler(
    refOrRefs: Element | null | (Element | null)[],
    handleClickOutside?: () => void,
    extraDeps: any[] = []
): void {
    const allRefs = Array.isArray(refOrRefs) ? refOrRefs : [refOrRefs]

    useEffect(() => {
        function handleClick(event: Event): void {
            if (exceptions.some((exception) => (event.target as Element).matches(exception))) {
                return
            }
            if (allRefs.some((ref) => ref?.contains(event.target as Element))) {
                return
            }
            handleClickOutside?.()
        }

        if (allRefs.length > 0) {
            // only attach event listeners if there's something to track
            document.addEventListener('mousedown', handleClick)
            return () => document.removeEventListener('mousedown', handleClick)
        }
    }, [...allRefs, ...extraDeps])
}
