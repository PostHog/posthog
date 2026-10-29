import { useActions, useValues } from 'kea'

import { IconBookmark, IconX } from '@posthog/icons'
import { DropdownMenuItem, DropdownMenuList, MenuEmpty } from '@posthog/quill'

import { filterBarLogic } from './filterBarLogic'

/** The name prompt for saving the current filters. The menu's search field is where the name is typed. */
export function FilterBarSaveRows(): JSX.Element {
    const { query, completeFilters } = useValues(filterBarLogic)
    const { saveCurrentFilters, cancelSaving } = useActions(filterBarLogic)
    const name = query.trim()

    return (
        <DropdownMenuList>
            {name ? (
                <DropdownMenuItem onClick={() => saveCurrentFilters(name)} data-attr="filter-bar-save-confirm">
                    <IconBookmark />
                    <span className="truncate">
                        Save {completeFilters.length === 1 ? 'this filter' : `these ${completeFilters.length} filters`}{' '}
                        as "{name}"
                    </span>
                </DropdownMenuItem>
            ) : (
                <MenuEmpty>Type a name to save the current filters</MenuEmpty>
            )}
            <DropdownMenuItem closeOnClick={false} onClick={cancelSaving} data-attr="filter-bar-save-cancel">
                <IconX />
                Cancel
            </DropdownMenuItem>
        </DropdownMenuList>
    )
}
