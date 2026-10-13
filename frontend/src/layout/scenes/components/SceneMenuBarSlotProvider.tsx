import { PropsWithChildren, createContext, useContext, useLayoutEffect, useState } from 'react'

/**
 * Under the Today layout the scene title section exposes a slot below its header, and the scene menu bar portals into
 * it. Scenes render the bar and the title as unrelated siblings, so each scene shares the slot element through this
 * context.
 */
interface SceneMenuBarSlotContextValue {
    slot: HTMLElement | null
    setSlot: (slot: HTMLElement | null) => void
}

const SceneMenuBarSlotContext = createContext<SceneMenuBarSlotContextValue>({ slot: null, setSlot: () => {} })

export function SceneMenuBarSlotProvider({ children }: PropsWithChildren): JSX.Element {
    const [slot, setSlot] = useState<HTMLElement | null>(null)
    return <SceneMenuBarSlotContext.Provider value={{ slot, setSlot }}>{children}</SceneMenuBarSlotContext.Provider>
}

export function useRegisterSceneMenuBarSlot(element: HTMLElement | null): void {
    const { setSlot } = useContext(SceneMenuBarSlotContext)
    useLayoutEffect(() => {
        if (!element) {
            return
        }
        setSlot(element)
        return () => setSlot(null)
    }, [element, setSlot])
}

export function useSceneMenuBarSlot(): HTMLElement | null {
    return useContext(SceneMenuBarSlotContext).slot
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
