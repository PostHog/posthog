import { ReactNode, createContext, useContext } from 'react'

import { ComponentPanelVisibility } from './componentPanels'

export type ComponentPanelState = {
    componentPanels: ComponentPanelVisibility
    showEditPanel: boolean
    showViewPanel: boolean
    jupyterOutputPrompt?: (isError: boolean) => ReactNode
}

export const ComponentPanelContext = createContext<ComponentPanelState | null>(null)

export function useComponentPanelState(): ComponentPanelState | null {
    return useContext(ComponentPanelContext)
}
