import { DropdownMenuItem } from '@posthog/quill'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { FilterBarCohortFieldItem } from './FilterBarCohortFieldItem'
import { useFilterBarFieldPicker } from './filterBarFieldPicker'
import { FilterBarField } from './filterBarTypes'

/** A field to filter on. Picking it moves the menu on to the field's values, so the menu stays open. */
export function FilterBarFieldItem({
    field,
    source,
}: {
    field: FilterBarField
    source: 'popular' | 'search'
}): JSX.Element {
    const { purpose, pick } = useFilterBarFieldPicker()
    if (purpose === 'filter' && field.categoryId === 'cohorts') {
        return <FilterBarCohortFieldItem field={field} source={source} />
    }
    return (
        <DropdownMenuItem
            closeOnClick={false}
            onClick={() => pick(field, source)}
            data-attr={`filter-bar-field-${source}`}
        >
            <FilterBarCategoryIcon categoryId={field.categoryId} />
            <span className="truncate">{field.label}</span>
        </DropdownMenuItem>
    )
}
