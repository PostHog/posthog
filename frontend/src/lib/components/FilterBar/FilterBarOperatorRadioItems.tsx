import { useActions } from 'kea'

import { DropdownMenuEmpty, DropdownMenuList, DropdownMenuRadioGroup, DropdownMenuRadioItem } from '@posthog/quill'

import { PropertyOperator } from '~/types'

import { filterOperator } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarOperatorOption, FilterBarItem } from './filterBarTypes'

/** The operators a filter's field allows, as radio rows in the chip's operator menu. */
export function FilterBarOperatorRadioItems({
    item,
    options,
}: {
    item: FilterBarItem
    options: FilterBarOperatorOption[]
}): JSX.Element {
    const { setItemOperator } = useActions(filterBarLogic)

    return (
        <DropdownMenuList>
            <DropdownMenuEmpty>No operator matches</DropdownMenuEmpty>
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
        </DropdownMenuList>
    )
}
