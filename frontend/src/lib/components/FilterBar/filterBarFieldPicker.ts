import { useActions } from 'kea'
import { createContext, useContext } from 'react'

import { filterBarLogic } from './filterBarLogic'
import { FilterBarAddSource, FilterBarField } from './filterBarTypes'

export interface FilterBarFieldPicker {
    purpose: 'filter' | 'breakdown'
    pick: (field: FilterBarField, source: FilterBarAddSource) => void
}

/** Lets a bar control reuse the add menu's field list. Without a provider, a picked field becomes a filter. */
export const FilterBarFieldPickerContext = createContext<FilterBarFieldPicker | null>(null)

export function useFilterBarFieldPicker(): FilterBarFieldPicker {
    const picker = useContext(FilterBarFieldPickerContext)
    const { addField } = useActions(filterBarLogic)
    return picker ?? { purpose: 'filter', pick: addField }
}
