import { useActions } from 'kea'
import { createContext, useContext } from 'react'

import { canBreakDownByCategory } from './filterBarBreakdownFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarAddSource, FilterBarCategoryId, FilterBarField } from './filterBarTypes'

export interface FilterBarFieldPicker {
    /** `replace-property` and `replace-event` change the field of a chip that exists. */
    purpose: 'filter' | 'breakdown' | 'replace-property' | 'replace-event'
    pick: (field: FilterBarField, source: FilterBarAddSource) => void
}

/** The categories a picker lists. A chip stays the kind it is, so a property chip can't turn into an event or SQL. */
export function pickerOffersCategory(
    purpose: FilterBarFieldPicker['purpose'],
    categoryId: FilterBarCategoryId,
    targetIsEvent: boolean
): boolean {
    switch (purpose) {
        case 'filter':
            return !(targetIsEvent && categoryId === 'events')
        case 'breakdown':
            return canBreakDownByCategory(categoryId)
        case 'replace-property':
            return categoryId !== 'events' && categoryId !== 'sql'
        case 'replace-event':
            return categoryId === 'events'
    }
}

/** Lets a bar control reuse the add menu's field list. Without a provider, a picked field becomes a filter. */
export const FilterBarFieldPickerContext = createContext<FilterBarFieldPicker | null>(null)

export function useFilterBarFieldPicker(): FilterBarFieldPicker {
    const picker = useContext(FilterBarFieldPickerContext)
    const { addField } = useActions(filterBarLogic)
    return picker ?? { purpose: 'filter', pick: addField }
}
