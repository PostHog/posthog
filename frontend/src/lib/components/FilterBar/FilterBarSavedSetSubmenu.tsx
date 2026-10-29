import { useActions } from 'kea'

import { IconBookmark, IconCheck, IconTrash } from '@posthog/icons'
import { DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { fieldFromFilter, operatorLabelForFilter, valueLabelForFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { filterBarSavedSetsLogic } from './filterBarSavedSetsLogic'
import { FilterBarSavedSet } from './filterBarTypes'

export function savedSetSummary(set: FilterBarSavedSet): string {
    return set.filters
        .map((filter) => {
            const field = fieldFromFilter(filter)
            if (!field) {
                return null
            }
            const value = valueLabelForFilter(filter).text
            return [field.label, operatorLabelForFilter(filter), value].filter(Boolean).join(' ')
        })
        .filter(Boolean)
        .join(', ')
}

/** A saved set says what it holds under its name, so a person can check it before it replaces the filters in the bar. */
export function FilterBarSavedSetSubmenu({ set }: { set: FilterBarSavedSet }): JSX.Element {
    const { applySavedSet } = useActions(filterBarLogic)
    const { deleteSavedSet } = useActions(filterBarSavedSetsLogic)

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger description={savedSetSummary(set)} data-attr="filter-bar-saved-set">
                <IconBookmark />
                <span className="truncate">{set.name}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuItem onClick={() => applySavedSet(set.id)} data-attr="filter-bar-saved-set-apply">
                    <IconCheck />
                    Use these filters
                </DropdownMenuItem>
                <DropdownMenuItem
                    variant="destructive"
                    closeOnClick={false}
                    onClick={() => deleteSavedSet(set.id)}
                    data-attr="filter-bar-saved-set-delete"
                >
                    <IconTrash />
                    Delete
                </DropdownMenuItem>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
