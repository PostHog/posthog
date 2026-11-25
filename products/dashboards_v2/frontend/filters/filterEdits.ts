import type { Dashboard, DashboardFilter } from '../dashboard/dashboardTypes'

/** Edits to which filters a dashboard has. A filter's value is not an edit: each viewer picks their own. */
export type FilterEdit =
    | { edit: 'setAllowFilters'; allowed: boolean }
    | { edit: 'addFilter'; filter: Omit<DashboardFilter, 'id'> }
    | { edit: 'removeFilter'; id: string }

function newFilterId(filters: DashboardFilter[]): string {
    const taken = new Set(filters.map((filter) => filter.id))
    let n = filters.length + 1
    while (taken.has(`filter${n}`)) {
        n++
    }
    return `filter${n}`
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
