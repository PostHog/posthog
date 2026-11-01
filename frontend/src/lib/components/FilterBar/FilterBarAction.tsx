import type { ComponentType } from 'react'

import { useFilterBarControl } from './filterBarControls'

export interface FilterBarActionProps {
    id: string
    label: string
    icon: ComponentType
    onSelect: () => void
}

/** A row in the bar's add menu that runs a host action, such as opening a settings modal. It renders no chip. */
export function FilterBarAction({ id, label, icon, onSelect }: FilterBarActionProps): null {
    useFilterBarControl({ id, label, icon, hasValue: false, open: onSelect, clear: () => {} })
    return null
}
