import { createRef, useEffect, useRef } from 'react'

export function useKeyboardNavigation<R extends HTMLElement = HTMLElement, I extends HTMLElement = HTMLElement>(
    itemCount: number,
    activeItemIndex: number = -1,
    { enabled = true } = {}
): {
    referenceRef: React.RefObject<R>
    itemsRef: React.RefObject<React.RefObject<I>[]>
    options?: { enabled: boolean }
} {
    const focusedItemIndexRef = useRef(activeItemIndex)
    const referenceRef = useRef<R>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))

    useEffect(() => {
        focusedItemIndexRef.current = activeItemIndex
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
                if (focusedItemIndexRef.current < itemCount - 1) {
                    focusedItemIndexRef.current += 1
                    focus(focusedItemIndexRef.current)
                    e.preventDefault()
                }
            } else if (e.key === 'ArrowUp') {
                if (focusedItemIndexRef.current >= 0) {
                    focusedItemIndexRef.current -= 1
                    focus(focusedItemIndexRef.current)
                    e.preventDefault()
                }
            }
        }

        const controller = new AbortController()

        referenceRef.current?.addEventListener('keydown', handleKeyDown, { signal: controller.signal })
        for (const item of itemsRef.current) {
            item?.current?.addEventListener('keydown', handleKeyDown, { signal: controller.signal })
        }
        return () => {
            controller.abort()
        }
    }, [itemCount, enabled])

    return { referenceRef, itemsRef }
}
