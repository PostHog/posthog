import { useEffect } from 'react'

const exceptions = ['.ant-select-dropdown *', '.click-outside-block', '.click-outside-block *']

export function useOutsideClickHandler(
    refOrRefs: React.MutableRefObject<any> | Element | null | (React.MutableRefObject<any> | Element | null)[],
    handleClickOutside?: (event: Event) => void,
    extraDeps: any[] = []
): void {
    const allRefs = Array.isArray(refOrRefs) ? refOrRefs : [refOrRefs]

    useEffect(() => {
        function handleClick(event: Event): void {
            if (exceptions.some((exception) => (event.target as Element).matches(exception))) {
                return
            }
            if (
                allRefs.some((maybeRef) => {
                    const ref = maybeRef && 'current' in maybeRef ? maybeRef.current : maybeRef
                    return ref && `contains` in ref && ref.contains(event.target as Element)
                })
            ) {
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
