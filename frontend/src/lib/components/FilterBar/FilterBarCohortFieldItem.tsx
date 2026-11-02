import { useActions, useValues } from 'kea'

import { DropdownMenuCheckboxItem } from '@posthog/quill'

import { filterBarLogic } from './filterBarLogic'
import { FilterBarAddSource, FilterBarField } from './filterBarTypes'

/**
 * A cohort to filter on, ticked while the bar has it. Each cohort is its own chip, because the bar joins filters with
 * AND and a cohort filter holds one cohort.
 */
export function FilterBarCohortFieldItem({
    field,
    source,
}: {
    field: FilterBarField
    source: FilterBarAddSource
}): JSX.Element {
    const { cohortItemIds } = useValues(filterBarLogic)
    const { toggleCohortField } = useActions(filterBarLogic)
    return (
        <DropdownMenuCheckboxItem
            checked={cohortItemIds[field.key] != null}
            onCheckedChange={() => toggleCohortField(field, source)}
            data-attr={`filter-bar-field-${source}`}
        >
            <span className="truncate">{field.label}</span>
        </DropdownMenuCheckboxItem>
    )
}
