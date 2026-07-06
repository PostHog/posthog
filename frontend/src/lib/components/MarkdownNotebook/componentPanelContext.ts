import { createContext, useContext } from 'react'

import { ComponentPanelVisibility } from './componentPanels'

export type ComponentPanelState = {
    componentPanels: ComponentPanelVisibility
    showEditPanel: boolean
    showViewPanel: boolean
}

export const ComponentPanelContext = createContext<ComponentPanelState | null>(null)

export function useComponentPanelState(): ComponentPanelState | null {
    return useContext(ComponentPanelContext)
}
