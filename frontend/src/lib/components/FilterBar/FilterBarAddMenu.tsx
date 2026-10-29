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
import { FilterBarStage, filterBarLogic } from './filterBarLogic'
import { FilterBarSaveRows } from './FilterBarSaveRows'
import { FilterBarValueRows } from './FilterBarValueRows'

function inputCopyForStage(stage: FilterBarStage, fieldLabel?: string): { label: string; placeholder: string } {
    switch (stage) {
        case 'values':
            return { label: 'Search or type a value', placeholder: `${fieldLabel ?? 'Value'}…` }
        case 'save':
            return { label: 'Name for these filters', placeholder: 'Name for these filters…' }
        default:
            return { label: 'Search fields', placeholder: 'Filter by…' }
    }
}

/**
 * The picker behind the add button. One menu, one search field, three screens: the fields to filter on, then
 * the values of the field just picked, and the name prompt when saving the current filters.
 */
export function FilterBarAddMenu(): JSX.Element {
    const { menuOpen, query, stage, items, editingItem } = useValues(filterBarLogic)
    const { setMenuOpen, setQuery } = useActions(filterBarLogic)
    const hasFilters = items.length > 0

    const input = inputCopyForStage(stage, editingItem ? fieldFromFilter(editingItem.filter)?.label : undefined)

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
                    header={<DropdownMenuInput aria-label={input.label} placeholder={input.placeholder} />}
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
