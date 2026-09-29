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
    const referenceRef = useRef<R>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))

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
            const targetItemIndex = itemsRef.current.findIndex((item) => item.current === e.target)
            if (e.defaultPrevented || (e.target !== referenceRef.current && targetItemIndex === -1)) {
                return
            }
            let fromIndex = targetItemIndex
            if (e.target === referenceRef.current) {
                // A closed menu has no mounted items, so leave the key to the parent menu or the page.
                if (!itemsRef.current.some((item) => item.current)) {
                    return
                }
                fromIndex = activeItemIndex
            }
            // Refs without a mounted button, such as a custom item, cannot take focus.
            if (e.key === 'ArrowDown') {
                const nextIndex = itemsRef.current.findIndex((item, i) => i > fromIndex && item.current)
                if (nextIndex > -1) {
                    focus(nextIndex)
                    e.preventDefault()
                }
            } else if (e.key === 'ArrowUp') {
                if (fromIndex >= 0) {
                    focus(itemsRef.current.findLastIndex((item, i) => i < fromIndex && item.current))
                    e.preventDefault()
                }
            }
        }

        const controller = new AbortController()

        // A submenu trigger handles keys before its parent menu sees the bubbled event.
        referenceRef.current?.addEventListener('keydown', handleKeyDown, { signal: controller.signal })
        // Portal items mount after this effect, so resolve their refs when a key is pressed.
        referenceRef.current?.ownerDocument.addEventListener('keydown', handleKeyDown, { signal: controller.signal })
        return () => {
            controller.abort()
        }
    }, [enabled, activeItemIndex])

    return { referenceRef, itemsRef }
}
