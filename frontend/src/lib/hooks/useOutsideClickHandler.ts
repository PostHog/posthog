import { useEffect } from 'react'

const exceptions = ['.ant-select-dropdown *', '.click-outside-block', '.click-outside-block *', '.ant-modal-root *']

export function useOutsideClickHandler(
    refOrRefs: Element | null | (Element | null)[],
    handleClickOutside?: (event: Event) => void,
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
            handleClickOutside?.(event)
        }

        if (allRefs.length > 0) {
            // Only attach event listeners if there's something to track
            document.addEventListener('click', handleClick)
            return () => document.removeEventListener('click', handleClick)
        }
    }, [...allRefs, ...extraDeps])
}
