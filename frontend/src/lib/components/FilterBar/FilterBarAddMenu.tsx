import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FilterBarFieldRows } from './FilterBarFieldRows'
import { fieldFromFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarSaveRows } from './FilterBarSaveRows'
import { FilterBarValueRows } from './FilterBarValueRows'

/**
 * The picker behind the add button. One menu, one search field, three screens: the fields to filter on, then
 * the values of the field just picked, and the name prompt when saving the current filters.
 */
export function FilterBarAddMenu(): JSX.Element {
    const { menuOpen, query, stage, items, editingItem } = useValues(filterBarLogic)
    const { setMenuOpen, setQuery } = useActions(filterBarLogic)
    const hasFilters = items.length > 0

    const editingField = editingItem ? fieldFromFilter(editingItem.filter) : null
    const placeholder =
        stage === 'values'
            ? `${editingField?.label ?? 'Value'}…`
            : stage === 'save'
              ? 'Name for these filters…'
              : 'Filter by…'
    const inputLabel =
        stage === 'values' ? 'Search or type a value' : stage === 'save' ? 'Name for these filters' : 'Search fields'

    return (
        <DropdownMenuFilterProvider filter={null} value={query} onValueChange={setQuery} autoHighlight>
            <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen} modal={false}>
                <DropdownMenuTrigger
                    render={
                        hasFilters ? (
                            <Button size="icon" variant="outline" aria-label="Add filter" tooltip="Add filter" />
                        ) : (
                            <Button variant="outline" />
                        )
                    }
                    data-attr="filter-bar-add"
                >
                    <IconFilter />
                    {!hasFilters && 'Filter'}
                </DropdownMenuTrigger>
                <DropdownMenuContent
                    className="w-72"
                    header={<DropdownMenuInput aria-label={inputLabel} placeholder={placeholder} />}
                >
                    {stage === 'values' && editingItem ? (
                        <FilterBarValueRows item={editingItem} query={query} />
                    ) : stage === 'save' ? (
                        <FilterBarSaveRows />
                    ) : (
                        <FilterBarFieldRows />
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </DropdownMenuFilterProvider>
    )
}
