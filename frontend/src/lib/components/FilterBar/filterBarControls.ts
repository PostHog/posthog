import { createContext, useContext, useEffect, useRef } from 'react'

import { FilterBarControl } from './filterBarTypes'

export interface FilterBarControlsContextValue {
    controls: FilterBarControl[]
    register: (control: FilterBarControl) => () => void
}

export const FilterBarControlsContext = createContext<FilterBarControlsContextValue>({
    controls: [],
    register: () => () => {},
})

export function useFilterBarControls(): FilterBarControl[] {
    return useContext(FilterBarControlsContext).controls
}

/**
 * Adds a control to the enclosing `FilterBar`. The bar re-reads the control only when its id, label, icon or value
 * state changes, so `open` and `clear` can be new functions on every render.
 */
export function useFilterBarControl(control: FilterBarControl): void {
    const { register } = useContext(FilterBarControlsContext)
    const latest = useRef(control)
    useEffect(() => {
        latest.current = control
    })
    const { id, label, icon, hasValue, persistent } = control
    useEffect(
        () =>
            register({
                id,
                label,
                icon,
                hasValue,
                persistent,
                open: () => latest.current.open(),
                clear: () => latest.current.clear(),
            }),
        [register, id, label, icon, hasValue, persistent]
    )
}
