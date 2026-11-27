import type { Dashboard, SavedFilter } from '../dashboard/document/dashboardTypes'

/** Edits to which filters a dashboard has. A filter's value is not an edit: each viewer picks their own. */
export type FilterEdit =
    | { edit: 'setAllowFilters'; allowed: boolean }
    | { edit: 'addFilter'; filter: Omit<SavedFilter, 'id'> }
    | { edit: 'removeFilter'; id: string }

// Random rather than counted: a viewer's value is kept by id, so a reused id would hand a removed filter's value to
// the filter added after it.
function newFilterId(filters: SavedFilter[]): string {
    const taken = new Set(filters.map((filter) => filter.id))
    let id: string
    do {
        id = `filter-${Math.random().toString(36).slice(2, 10)}`
    } while (taken.has(id))
    return id
}

export function applyFilterEdit(dashboard: Dashboard, edit: FilterEdit): Dashboard {
    const filters = dashboard.filters ?? []
    switch (edit.edit) {
        case 'setAllowFilters':
            return { ...dashboard, allowFilters: edit.allowed }
        case 'addFilter':
            return { ...dashboard, filters: [...filters, { ...edit.filter, id: newFilterId(filters) }] }
        case 'removeFilter':
            return { ...dashboard, filters: filters.filter((filter) => filter.id !== edit.id) }
    }
}
