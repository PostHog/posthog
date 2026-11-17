import { PropsWithChildren, createContext, useContext, useLayoutEffect, useState } from 'react'

/**
 * Under the Today layout the scene title section exposes a slot after the scene name, and the scene menu bar portals
 * into it. Scenes render the bar and the title as unrelated siblings, so each scene shares the slot element through this
 * context.
 */
interface SceneMenuBarSlotContextValue {
    slot: HTMLElement | null
    setSlot: (slot: HTMLElement | null) => void
    /** Whether a menu bar fills the slot, so the title can leave out what the bar already offers. */
    filled: boolean
    setFilled: (filled: boolean) => void
    /** The title row's actions area, which scene actions fill with their pinned actions under `scene-actions`. */
    pinnedSlot: HTMLElement | null
    setPinnedSlot: (slot: HTMLElement | null) => void
    /** Whether pinned actions fill the title row, so the title leaves out the scene's own `actions`. */
    pinnedFilled: boolean
    setPinnedFilled: (filled: boolean) => void
}

const SceneMenuBarSlotContext = createContext<SceneMenuBarSlotContextValue>({
    slot: null,
    setSlot: () => {},
    filled: false,
    setFilled: () => {},
    pinnedSlot: null,
    setPinnedSlot: () => {},
    pinnedFilled: false,
    setPinnedFilled: () => {},
})

export function SceneMenuBarSlotProvider({ children }: PropsWithChildren): JSX.Element {
    const [slot, setSlot] = useState<HTMLElement | null>(null)
    const [filled, setFilled] = useState(false)
    const [pinnedSlot, setPinnedSlot] = useState<HTMLElement | null>(null)
    const [pinnedFilled, setPinnedFilled] = useState(false)
    return (
        <SceneMenuBarSlotContext.Provider
            value={{ slot, setSlot, filled, setFilled, pinnedSlot, setPinnedSlot, pinnedFilled, setPinnedFilled }}
        >
            {children}
        </SceneMenuBarSlotContext.Provider>
    )
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

export function useFillSceneMenuBarSlot(filling: boolean): void {
    const { setFilled } = useContext(SceneMenuBarSlotContext)
    useLayoutEffect(() => {
        if (!filling) {
            return
        }
        setFilled(true)
        return () => setFilled(false)
    }, [filling, setFilled])
}

export function useSceneMenuBarSlotFilled(): boolean {
    return useContext(SceneMenuBarSlotContext).filled
}

export function useRegisterScenePinnedSlot(element: HTMLElement | null): void {
    const { setPinnedSlot } = useContext(SceneMenuBarSlotContext)
    useLayoutEffect(() => {
        if (!element) {
            return
        }
        setPinnedSlot(element)
        return () => setPinnedSlot(null)
    }, [element, setPinnedSlot])
}

export function useScenePinnedSlot(): HTMLElement | null {
    return useContext(SceneMenuBarSlotContext).pinnedSlot
}

export function useFillScenePinnedSlot(filling: boolean): void {
    const { setPinnedFilled } = useContext(SceneMenuBarSlotContext)
    useLayoutEffect(() => {
        if (!filling) {
            return
        }
        setPinnedFilled(true)
        return () => setPinnedFilled(false)
    }, [filling, setPinnedFilled])
}

export function useScenePinnedSlotFilled(): boolean {
    return useContext(SceneMenuBarSlotContext).pinnedFilled
}
