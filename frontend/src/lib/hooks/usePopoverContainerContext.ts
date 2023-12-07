import { createContext, RefObject, useContext } from 'react'

/**
 * PopoverContainerContext
 *
 * Typically popovers are portaled to the root of the document, but sometimes
 * you want to portal them to a specific container. This context allows you to
 * specify a container for popovers to portal to.
 *
 * For example the Toolbar or the SessionRecordingPlayer so that in full screen mode
 * the popover is not portaled to the root of the document but to the player.
 */

export const PopoverContainerContext = createContext<RefObject<HTMLElement> | undefined>(undefined)

export const usePopoverContainerContext = (): RefObject<HTMLElement> | undefined => {
    return useContext(PopoverContainerContext)
}
