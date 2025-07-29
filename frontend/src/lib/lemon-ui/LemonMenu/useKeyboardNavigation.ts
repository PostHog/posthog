import { createRef, useEffect, useRef, useState } from 'react'

export function useKeyboardNavigation<R extends HTMLElement = HTMLElement, I extends HTMLElement = HTMLElement>(
    itemCount: number,
    activeItemIndex: number = -1,
    { enabled = true } = {}
): {
    referenceRef: React.RefObject<R>
    itemsRef: React.RefObject<React.RefObject<I>[]>
    options?: { enabled: boolean }
} {
    const [focusedItemIndex, setFocusedItemIndex] = useState(activeItemIndex)
    const referenceRef = useRef<R>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))

    useEffect(() => {
        setFocusedItemIndex(activeItemIndex)
    }, [activeItemIndex])

    function focus(itemIndex: number): void {
        if (itemIndex > -1) {
            itemsRef.current[itemIndex].current?.focus()
        } else {
            referenceRef.current?.focus()
        }
    }

    useEffect(() => {
        if (!enabled) {
            return
        }

        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowDown') {
                if (focusedItemIndex < itemCount - 1) {
                    focus(focusedItemIndex + 1)
                    setFocusedItemIndex(focusedItemIndex + 1)
                    e.preventDefault() // Prevents scroll
                }
            } else if (e.key === 'ArrowUp') {
                if (focusedItemIndex >= 0) {
                    focus(focusedItemIndex - 1)
                    setFocusedItemIndex(focusedItemIndex - 1)
                    e.preventDefault() // Prevents scroll
                }
            }
        }

        referenceRef.current?.addEventListener('keydown', handleKeyDown)
        for (const item of itemsRef.current) {
            item?.current?.addEventListener('keydown', handleKeyDown)
        }
        return () => {
            referenceRef.current?.removeEventListener('keydown', handleKeyDown)
            for (const item of itemsRef.current) {
                item?.current?.removeEventListener('keydown', handleKeyDown)
            }
        }
    }, [focusedItemIndex, itemCount, enabled])

    return { referenceRef, itemsRef }
}
