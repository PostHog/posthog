import { useActions } from 'kea'

import { DropdownMenuItem } from '@posthog/quill'

import { AnyPropertyFilter } from '~/types'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { fieldFromFilter, operatorLabelForFilter, valueLabelForFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'

/** A recent filter reads as a sentence, "Browser is Chrome", so one click applies it whole. */
export function FilterBarRecentFilterItem({ filter }: { filter: AnyPropertyFilter }): JSX.Element | null {
    const { addFilter } = useActions(filterBarLogic)
    const field = fieldFromFilter(filter)
    if (!field) {
        return null
    }
    return (
        <DropdownMenuItem onClick={() => addFilter(filter, 'recent')} data-attr="filter-bar-recent">
            <FilterBarCategoryIcon categoryId={field.categoryId} />
            <span className="truncate">{field.label}</span>
            <span className="truncate text-muted-foreground">
                {operatorLabelForFilter(filter)} {valueLabelForFilter(filter).text}
            </span>
        </DropdownMenuItem>
    )
}
