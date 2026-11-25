import { createContext, useContext } from 'react'

import type { DropTarget } from './dropTargets'

export interface GridDragState {
    dropTarget: DropTarget | null
    setDropTarget: (dropTarget: DropTarget | null) => void
}

// The drop target changes on every cell a dragged tile crosses, so it has its own context: tiles that only read the
// dashboard do not re-render during a drag.
export const GridDragContext = createContext<GridDragState | null>(null)

export function useGridDrag(): GridDragState {
    const drag = useContext(GridDragContext)
    if (!drag) {
        throw new Error('useGridDrag must be used inside a GridDragContext provider')
    }
    return drag
}
