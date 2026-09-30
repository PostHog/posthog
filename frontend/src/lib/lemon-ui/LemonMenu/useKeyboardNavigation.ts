import { FocusEventHandler, KeyboardEvent, KeyboardEventHandler, createRef, useRef } from 'react'

export function useKeyboardNavigation<I extends HTMLElement = HTMLElement>(
    itemCount: number,
    activeItemIndex: number = -1,
    { enabled = true } = {}
): {
    referenceRef: React.RefObject<HTMLElement>
    itemsRef: React.RefObject<React.RefObject<I>[]>
    onTriggerFocus: FocusEventHandler<HTMLElement>
    onTriggerKeyDown: KeyboardEventHandler<HTMLElement>
    onItemsKeyDown: KeyboardEventHandler<HTMLElement>
} {
    const referenceRef = useRef<HTMLElement>(null)
    const focusedTriggerRef = useRef<HTMLElement | null>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))
    // A menu can gain items after its first render, for example when its data loads.
    while (itemsRef.current.length < itemCount) {
        itemsRef.current.push(createRef<I>())
    }

    function moveFocus(e: KeyboardEvent<HTMLElement>, fromIndex: number): void {
        if (!enabled || e.defaultPrevented) {
            return
        }
        let target: HTMLElement | null = null
        if (e.key === 'ArrowDown') {
            target = itemsRef.current.find((item, i) => i > fromIndex && item.current)?.current ?? null
        } else if (e.key === 'ArrowUp' && fromIndex >= 0) {
            target =
                itemsRef.current.findLast((item, i) => i < fromIndex && item.current)?.current ??
                focusedTriggerRef.current ??
                referenceRef.current
        }
        if (target) {
            target.focus()
            e.preventDefault()
        }
    }

    return {
        referenceRef,
        itemsRef,
        onTriggerFocus: (e) => {
            // The positioning ref can point at a wrapper, so remember the element that actually took focus.
            focusedTriggerRef.current = e.target
        },
        onTriggerKeyDown: (e) => {
            // A closed submenu leaves arrow keys to its parent menu.
            if (itemsRef.current.some((item) => item.current)) {
                moveFocus(e, activeItemIndex)
            }
        },
        onItemsKeyDown: (e) => {
            const itemIndex = itemsRef.current.findIndex((item) => item.current === e.target)
            if (itemIndex >= 0) {
                moveFocus(e, itemIndex)
            }
        },
    }
}
