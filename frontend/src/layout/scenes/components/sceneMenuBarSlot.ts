import { useLayoutEffect, useState, useSyncExternalStore } from 'react'

/**
 * Under the Today layout the scene title section exposes a slot below its header, and the scene menu bar portals into
 * it. Scenes render the bar and the title as unrelated siblings, so the slot element goes through this store.
 */
let slotElement: HTMLElement | null = null
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
}

function getSnapshot(): HTMLElement | null {
    return slotElement
}

function notify(): void {
    listeners.forEach((listener) => listener())
}

export function useRegisterSceneMenuBarSlot(element: HTMLElement | null): void {
    useLayoutEffect(() => {
        if (!element) {
            return
        }
        slotElement = element
        notify()
        return () => {
            if (slotElement === element) {
                slotElement = null
                notify()
            }
        }
    }, [element])
}

export function useSceneMenuBarSlot(): HTMLElement | null {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/**
 * A negative top margin equal to the parent's flex gap, so the slot sits flush under the header. Scenes nest the title
 * in parents with different gaps, so the gap is read from the DOM instead of assumed.
 */
export function useSceneMenuBarSlotMarginTop(element: HTMLElement | null): number {
    const [marginTop, setMarginTop] = useState(0)
    useLayoutEffect(() => {
        const parent = element?.parentElement
        if (!parent) {
            return
        }
        const gap = parseFloat(getComputedStyle(parent).rowGap)
        setMarginTop(Number.isFinite(gap) ? -gap : 0)
    }, [element])
    return marginTop
}
