import { useLayoutEffect, useRef, useState } from 'react'

import { IconChevronDown, IconFilter } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Separator, Text } from '@posthog/quill'

import type { SavedFilter } from '../../dashboard/document/dashboardTypes'
import type { FilterDefinition } from '../filterDefinition'
import { activeFirst, filterValue } from '../filtersContext'
import { AddFilterMenu } from './AddFilterMenu'
import { FilterPill } from './FilterPill'

export type FilterBarProps = {
    filters: SavedFilter[]
    types: FilterDefinition[]
    values: Record<string, unknown>
    onValueChange: (id: string, value: unknown) => void
    onAdd?: (filter: Omit<SavedFilter, 'id'>) => void
    onRemove?: (id: string) => void
}

/**
 * The default arrangement of the filter pieces: one "N filters" button that opens every filter, with the add filter
 * menu inside. A page that wants another layout composes `FilterPill` and `AddFilterMenu` itself.
 */
export function FilterBar({
    filters,
    types,
    values,
    onValueChange,
    onAdd,
    onRemove,
}: FilterBarProps): JSX.Element | null {
    const [open, setOpen] = useState(false)
    // A filter this bar just added stays on the bar with its picker open until it has a value. Undo or redo bringing
    // a filter back does not count as added here.
    const [pendingId, setPendingId] = useState<string | null>(null)
    const addedHere = useRef(false)
    const knownIds = useRef(new Set(filters.map((filter) => filter.id)))
    useLayoutEffect(() => {
        if (addedHere.current) {
            const added = filters.find((filter) => !knownIds.current.has(filter.id))
            if (added) {
                setPendingId(added.id)
            }
        }
        knownIds.current = new Set(filters.map((filter) => filter.id))
        addedHere.current = false
    }, [filters])

    const pendingHasValue = pendingId !== null && filterValue(values, pendingId) !== undefined
    useLayoutEffect(() => {
        if (pendingHasValue) {
            setPendingId(null)
        }
    }, [pendingHasValue])
    // Clear all remounts the pills, so an editor holding drafts of the cleared value starts again from nothing.
    const [cleared, setCleared] = useState(0)

    const pending = filters.find((filter) => filter.id === pendingId && !pendingHasValue)
    const listed = activeFirst(filters, values).filter((filter) => filter !== pending)
    if (filters.length === 0 && !onAdd) {
        return null
    }

    const pill = (filter: SavedFilter): JSX.Element => (
        <FilterPill
            key={`${filter.id}-${cleared}`}
            filter={filter}
            types={types}
            value={filterValue(values, filter.id)}
            onChange={(value) => onValueChange(filter.id, value)}
            onRemove={onRemove && (() => onRemove(filter.id))}
            defaultOpen={filter === pending}
        />
    )
    const addMenu = onAdd && (
        <AddFilterMenu
            filters={filters}
            types={types}
            onAdd={(filter) => {
                addedHere.current = true
                setOpen(false)
                onAdd(filter)
            }}
        />
    )

    if (listed.length === 0) {
        return (
            <div className="flex items-center gap-2" data-attr="dashboard-v2-filter-bar">
                {pending && pill(pending)}
                {addMenu}
            </div>
        )
    }

    const countLabel = listed.length === 1 ? '1 filter' : `${listed.length} filters`
    const withValue = listed.filter((filter) => filterValue(values, filter.id) !== undefined)
    return (
        <div className="flex items-center gap-2" data-attr="dashboard-v2-filter-bar">
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={<Button size="sm" variant="outline" data-attr="dashboard-v2-filters-trigger" />}
                >
                    <IconFilter />
                    <span>{countLabel}</span>
                    <IconChevronDown />
                </PopoverTrigger>
                <PopoverContent align="start" className="w-auto min-w-80 max-w-[min(40rem,90vw)] gap-0 p-0">
                    <div className="flex items-center justify-between gap-4 px-3 pt-2">
                        <Text size="sm" render={<span />}>
                            <span className="font-semibold">Filters</span>
                            <span className="text-muted-foreground"> · {countLabel}</span>
                        </Text>
                        {withValue.length > 0 && (
                            <Button
                                onClick={() => {
                                    withValue.forEach((filter) => onValueChange(filter.id, undefined))
                                    setCleared((count) => count + 1)
                                }}
                                data-attr="dashboard-v2-filters-clear"
                            >
                                Clear all
                            </Button>
                        )}
                    </div>
                    <div className="flex max-h-[60vh] flex-col items-start gap-2 overflow-y-auto p-3">
                        {listed.map(pill)}
                    </div>
                    {addMenu && (
                        <>
                            <Separator />
                            <div className="p-2">{addMenu}</div>
                        </>
                    )}
                </PopoverContent>
            </Popover>
            {pending && pill(pending)}
        </div>
    )
}
