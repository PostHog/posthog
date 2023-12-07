import { createContext, RefObject, useContext } from 'react'

export const PopoverContainerContext = createContext<RefObject<HTMLElement> | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const usePopoverContainerContext = (): RefObject<HTMLElement> | undefined => {
    return useContext(PopoverContainerContext)
}
