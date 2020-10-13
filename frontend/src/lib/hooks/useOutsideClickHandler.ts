import { useEffect, MutableRefObject } from 'react'

export function useOutsideClickHandler(
    refOrRefs: MutableRefObject<Element> | MutableRefObject<Element>[],
    handleClickOutside: () => void
): void {
    useEffect(() => {
        function handleClick(event: Event): void {
            const handleCondition = Array.isArray(refOrRefs)
                ? !refOrRefs.some((ref) => ref.current?.contains(event.target as Node))
                : !refOrRefs.current?.contains(event.target as Node)
            if (handleCondition) handleClickOutside()
        }
        document.addEventListener('mousedown', handleClick)
        return () => {
            document.removeEventListener('mousedown', handleClick)
        }
    }, [refOrRefs, handleClickOutside])
}
