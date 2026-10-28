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
}

const SceneMenuBarSlotContext = createContext<SceneMenuBarSlotContextValue>({
    slot: null,
    setSlot: () => {},
    filled: false,
    setFilled: () => {},
})

export function SceneMenuBarSlotProvider({ children }: PropsWithChildren): JSX.Element {
    const [slot, setSlot] = useState<HTMLElement | null>(null)
    const [filled, setFilled] = useState(false)
    return (
        <SceneMenuBarSlotContext.Provider value={{ slot, setSlot, filled, setFilled }}>
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
