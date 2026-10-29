import { useActions } from 'kea'

import { DropdownMenuItem } from '@posthog/quill'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarField } from './filterBarTypes'

/** A field to filter on. Picking it moves the menu on to the field's values, so the menu stays open. */
export function FilterBarFieldItem({
    field,
    source,
}: {
    field: FilterBarField
    source: 'popular' | 'search'
}): JSX.Element {
    const { addField } = useActions(filterBarLogic)
    return (
        <DropdownMenuItem
            closeOnClick={false}
            onClick={() => addField(field, source)}
            data-attr={`filter-bar-field-${source}`}
        >
            <FilterBarCategoryIcon categoryId={field.categoryId} />
            <span className="truncate">{field.label}</span>
        </DropdownMenuItem>
    )
}
