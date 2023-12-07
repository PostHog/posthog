import { createContext, useContext } from 'react'

export const PopoverContext = createContext<HTMLElement | ShadowRoot | undefined>(undefined)

// Currently there is no way to optionally get bound logics so this context allows us to maybe get a logic if it is "bound" via the provider
export const usePopoverContext = (): HTMLElement | ShadowRoot | undefined => {
    return useContext(PopoverContext)
}
