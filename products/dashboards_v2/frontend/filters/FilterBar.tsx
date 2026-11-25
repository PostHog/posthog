import { useLayoutEffect, useMemo, useRef } from 'react'

import type { DashboardFilter } from '../dashboard/dashboardTypes'
import { AddFilterMenu } from './AddFilterMenu'
import type { FilterDefinition } from './filterDefinition'
import { FilterPill } from './FilterPill'
import { activeFirst, filterValue } from './filtersContext'
import { FitRow } from './FitRow'

export interface FilterBarProps {
    filters: DashboardFilter[]
    types: FilterDefinition[]
    values: Record<string, unknown>
    onValueChange: (id: string, value: unknown) => void
    onAdd?: (filter: Omit<DashboardFilter, 'id'>) => void
    onRemove?: (id: string) => void
}

/**
 * The default arrangement of the filter pieces: pills with a value first, on one line that overflows into "+N filters",
 * after the add filter menu. A page that wants less composes `FilterPill`, `FitRow` and `AddFilterMenu` itself.
 */
export function FilterBar({
    filters,
    types,
    values,
    onValueChange,
    onAdd,
    onRemove,
}: FilterBarProps): JSX.Element | null {
    // The filter this bar just added mounts with its picker open. Undo or redo bringing a filter back does not.
    const addedHere = useRef(false)
    const knownIds = useRef(new Set(filters.map((filter) => filter.id)))
    const justAdded = addedHere.current ? filters.find((filter) => !knownIds.current.has(filter.id))?.id : undefined
    useLayoutEffect(() => {
        knownIds.current = new Set(filters.map((filter) => filter.id))
        addedHere.current = false
    }, [filters])
    const items = useMemo(
        () =>
            activeFirst(filters, values).map((filter) => ({
                id: filter.id,
                element: (
                    <FilterPill
                        filter={filter}
                        types={types}
                        value={filterValue(values, filter.id)}
                        onChange={(value) => onValueChange(filter.id, value)}
                        onRemove={onRemove && (() => onRemove(filter.id))}
                        defaultOpen={filter.id === justAdded}
                    />
                ),
            })),
        [filters, types, values, onValueChange, onRemove, justAdded]
    )
    if (filters.length === 0 && !onAdd) {
        return null
    }
    return (
        <div className="flex items-center gap-2" data-attr="dashboard-v2-filter-bar">
            {onAdd && (
                <AddFilterMenu
                    filters={filters}
                    types={types}
                    onAdd={(filter) => {
                        addedHere.current = true
                        onAdd(filter)
                    }}
                />
            )}
            <FitRow items={items} />
        </div>
    )
}
