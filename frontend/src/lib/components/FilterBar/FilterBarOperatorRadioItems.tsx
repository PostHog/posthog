import { useActions } from 'kea'

import { DropdownMenuRadioGroup, DropdownMenuRadioItem } from '@posthog/quill'

import { PropertyOperator, PropertyType } from '~/types'

import { filterOperator, operatorOptionsForFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarItem } from './filterBarTypes'

/** The operators a filter's field allows, as radio rows in the chip's operator menu. */
export function FilterBarOperatorRadioItems({
    item,
    propertyType,
}: {
    item: FilterBarItem
    propertyType: PropertyType | null
}): JSX.Element {
    const { setItemOperator } = useActions(filterBarLogic)
    const options = operatorOptionsForFilter(item.filter, propertyType)

    return (
        <DropdownMenuRadioGroup
            value={filterOperator(item.filter)}
            onValueChange={(operator) => setItemOperator(item.id, operator as PropertyOperator)}
        >
            {options.map((option) => (
                <DropdownMenuRadioItem key={option.value} value={option.value} data-attr="filter-bar-operator">
                    {option.label}
                </DropdownMenuRadioItem>
            ))}
        </DropdownMenuRadioGroup>
    )
}
