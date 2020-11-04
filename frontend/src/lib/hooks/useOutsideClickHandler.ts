import { useEffect, MutableRefObject } from 'react'

export function useOutsideClickHandler(
    refOrRefs: MutableRefObject<Element | null> | MutableRefObject<Element | null>[],
    handleClickOutside: () => void,
    deps: any[] = [refOrRefs]
): void {
    useEffect(() => {
        function handleClick(event: Event): void {
            if (refOrRefs) {
                const handleCondition = Array.isArray(refOrRefs)
                    ? !refOrRefs.some((ref) => ref.current?.contains(event.target as Node))
                    : !refOrRefs.current?.contains(event.target as Node)
                if (handleCondition) {
                    handleClickOutside()
                }
            }
        }

        document.addEventListener('mousedown', handleClick)
        return () => {
            document.removeEventListener('mousedown', handleClick)
        }
    }, deps)
}
