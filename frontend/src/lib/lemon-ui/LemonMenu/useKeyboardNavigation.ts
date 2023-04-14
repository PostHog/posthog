import { createRef, useEffect, useRef, useState } from 'react'

export function useKeyboardNavigation<R extends HTMLElement = HTMLElement, I extends HTMLElement = HTMLElement>(
    itemCount: number,
    activeItemIndex: number = -1
): {
    referenceRef: React.RefObject<R>
    itemsRef: React.RefObject<React.RefObject<I>[]>
} {
    const [focusedItemIndex, setFocusedItemIndex] = useState(activeItemIndex)
    const referenceRef = useRef<R>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))

    useEffect(() => {
        setFocusedItemIndex(activeItemIndex)
    }, [activeItemIndex])

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowDown') {
                if (focusedItemIndex < itemCount - 1) {
                    setFocusedItemIndex(focusedItemIndex + 1)
                    e.preventDefault() // Prevents scroll
                }
            } else if (e.key === 'ArrowUp') {
                if (focusedItemIndex >= 0) {
                    setFocusedItemIndex(focusedItemIndex - 1)
                    e.preventDefault() // Prevents scroll
                }
            }
        }

        ;(referenceRef.current as HTMLElement).addEventListener('keydown', handleKeyDown)
        for (const item of itemsRef.current) {
            item.current?.addEventListener('keydown', handleKeyDown)
        }
        return () => {
            ;(referenceRef.current as HTMLElement).removeEventListener('keydown', handleKeyDown)
            for (const item of itemsRef.current) {
                item.current?.removeEventListener('keydown', handleKeyDown)
            }
        }
    })

    useEffect(() => {
        if (focusedItemIndex > -1) {
            itemsRef.current[focusedItemIndex].current?.focus()
        } else {
            ;(referenceRef.current as HTMLElement).focus()
        }
    }, [focusedItemIndex])

    return { referenceRef, itemsRef }
}
