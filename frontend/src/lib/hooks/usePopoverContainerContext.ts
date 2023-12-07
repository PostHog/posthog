import { createContext, useContext } from 'react'

export const PopoverContainerContext = createContext<HTMLElement | null | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const usePopoverContainerContext = (): HTMLElement | null | undefined => {
    return useContext(PopoverContainerContext)
}
