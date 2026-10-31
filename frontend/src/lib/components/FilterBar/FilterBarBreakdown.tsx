import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconSort } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuTrigger,
    cn,
} from '@posthog/quill'

import { cohortsModel } from '~/models/cohortsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'

import { breakdownForField, fieldForBreakdown } from './filterBarBreakdownFields'
import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { FilterBarControlChip } from './FilterBarControlChip'
import { useFilterBarControl } from './filterBarControls'
import { FilterBarFieldPicker, FilterBarFieldPickerContext } from './filterBarFieldPicker'
import { FilterBarFieldRows } from './FilterBarFieldRows'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarMenuHeader } from './FilterBarMenuHeader'

export interface FilterBarBreakdownProps {
    breakdownFilter: BreakdownFilter | null | undefined
    onChange: (breakdownFilter: BreakdownFilter | null) => void
    label?: string
}

/**
 * One breakdown inside a `FilterBar`. A breakdown splits results instead of narrowing them, so it goes in the bar's
 * `trailing` slot, after the filters. It picks from the same field list as the add menu.
 */
export function FilterBarBreakdown({
    breakdownFilter,
    onChange,
    label = 'Breakdown by',
}: FilterBarBreakdownProps): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { query, browsingCategoryId, categoriesById } = useValues(filterBarLogic)
    const { setQuery, browseCategory } = useActions(filterBarLogic)
    const searchPlural = browsingCategoryId ? categoriesById[browsingCategoryId]?.plural : null
    const [open, setOpen] = useState(false)
    const field = fieldForBreakdown(breakdownFilter, (id) => cohortsById[id]?.name)

    useFilterBarControl({
        id: 'breakdown',
        label,
        icon: IconSort,
        hasValue: !!field,
        // The add menu closes on the same click, so wait a frame before opening, or its dismissal closes this too.
        open: () => requestAnimationFrame(() => setOpen(true)),
        clear: () => onChange(null),
    })

    const picker = useMemo<FilterBarFieldPicker>(
        () => ({
            purpose: 'breakdown',
            pick: (picked) => {
                onChange(breakdownForField(picked))
                setOpen(false)
            },
        }),
        [onChange]
    )

    if (!field && !open) {
        return null
    }

    return (
        <FilterBarControlChip
            icon={IconSort}
            label={label}
            onRemove={field ? () => onChange(null) : undefined}
            data-attr="filter-bar-breakdown"
        >
            <FilterBarFieldPickerContext.Provider value={picker}>
                <DropdownMenuFilterProvider filter={null} value={query} onValueChange={setQuery} autoHighlight>
                    <DropdownMenu
                        open={open}
                        onOpenChange={(next) => {
                            setOpen(next)
                            if (!next) {
                                setQuery('')
                                browseCategory(null)
                            }
                        }}
                        modal={false}
                    >
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="outline"
                                    className={cn('min-w-0 max-w-64', !field && 'text-muted-foreground')}
                                />
                            }
                            data-attr="filter-bar-breakdown-value"
                        >
                            {field && <FilterBarCategoryIcon categoryId={field.categoryId} className="shrink-0" />}
                            <span className="truncate">{field?.label ?? 'Pick a property'}</span>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                            className="w-72"
                            header={
                                <FilterBarMenuHeader
                                    label={searchPlural ? `Search ${searchPlural}` : 'Search fields'}
                                    placeholder={searchPlural ? `Search ${searchPlural}…` : 'Break down by…'}
                                />
                            }
                        >
                            <FilterBarFieldRows />
                        </DropdownMenuContent>
                    </DropdownMenu>
                </DropdownMenuFilterProvider>
            </FilterBarFieldPickerContext.Provider>
        </FilterBarControlChip>
    )
}
