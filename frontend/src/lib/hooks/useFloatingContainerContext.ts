import { RefObject, createContext, useContext, useEffect, useState } from 'react'

/**
 * Typically floating things like popovers and tooltips are portaled to the root of the document, but sometimes
 * you want to portal them to a specific container. This context allows you to
 * specify a container for popovers to portal to.
 *
 * For example the Toolbar or the SessionRecordingPlayer so that in full screen mode
 * the popover is not portaled to the root of the document but to the player.
 */

export const FloatingContainerContext = createContext<RefObject<HTMLElement> | undefined>(undefined)

export const useFloatingContainer = (): HTMLElement | null | undefined => {
    const ref = useContext(FloatingContainerContext)
    const [el, setEl] = useState<HTMLElement | null | undefined>(undefined)

    useEffect(() => {
        setEl(ref?.current)
    }, [ref])

    return el
}
