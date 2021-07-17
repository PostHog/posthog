import { useEffect } from 'react'

export function useOutsideClickHandler(
    refOrRefs: Element | null | (Element | null)[],
    handleClickOutside?: () => void,
    extraDeps: any[] = []
): void {
    const allRefs = Array.isArray(refOrRefs) ? refOrRefs : [refOrRefs]

    useEffect(() => {
        function handleClick(event: Event): void {
            if (!allRefs.some((ref) => ref?.contains(event.target as Node))) {
                handleClickOutside?.()
            }
        }

        if (allRefs.length > 0) {
            // only attach event listeners if there's something to track
            document.addEventListener('mousedown', handleClick)
            return () => document.removeEventListener('mousedown', handleClick)
        }
    }, [...allRefs, ...extraDeps])
}
