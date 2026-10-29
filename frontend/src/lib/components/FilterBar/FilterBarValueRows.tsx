import { useActions, useValues } from 'kea'

import {
    DropdownMenuCheckboxItem,
    DropdownMenuList,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    MenuEmpty,
} from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyFilterType } from '~/types'

import { categoryIdForFilter } from './filterBarCategories'
import { FilterBarCohortValueItems } from './FilterBarCohortValueItems'
import { FilterBarDateValueItems } from './FilterBarDateValueItems'
import {
    filterValues,
    groupTypeIndexForCategory,
    operatorLabelForFilter,
    propertyDefinitionTypeForCategory,
    valueKindForFilter,
} from './filterBarFields'
import { FilterBarListValueItems } from './FilterBarListValueItems'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarNumberValueItems } from './FilterBarNumberValueItems'
import { FilterBarOperatorRadioItems } from './FilterBarOperatorRadioItems'
import { FilterBarItem } from './filterBarTypes'

/**
 * The value picker for one filter: the values for its kind, then an operator submenu. The menu's search field
 * doubles as the place to type a value the list does not offer.
 */
export function FilterBarValueRows({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { describeProperty } = useValues(propertyDefinitionsModel)
    const { toggleItemValue } = useActions(filterBarLogic)
    const { filter } = item
    const categoryId = categoryIdForFilter(filter)
    const propertyType = categoryId
        ? describeProperty(
              filter.key ?? '',
              propertyDefinitionTypeForCategory(categoryId),
              groupTypeIndexForCategory(categoryId)
          )
        : null
    const kind = valueKindForFilter(filter, propertyType)

    let rows: JSX.Element | null
    switch (kind) {
        case 'none':
            rows = <MenuEmpty>This operator takes no value</MenuEmpty>
            break
        case 'boolean':
            rows = (
                <>
                    {['true', 'false'].map((value) => (
                        <DropdownMenuCheckboxItem
                            key={value}
                            checked={filterValues(filter).map(String).includes(value)}
                            closeOnClick
                            onCheckedChange={() => toggleItemValue(item.id, value, kind)}
                            data-attr="filter-bar-value"
                        >
                            {value}
                        </DropdownMenuCheckboxItem>
                    ))}
                </>
            )
            break
        case 'number':
            rows = <FilterBarNumberValueItems item={item} query={query} />
            break
        case 'date':
            rows = <FilterBarDateValueItems item={item} query={query} />
            break
        case 'cohort':
            rows = <FilterBarCohortValueItems item={item} query={query} />
            break
        case 'sql':
            rows = null
            break
        default:
            rows = <FilterBarListValueItems item={item} query={query} />
    }

    // The operator row comes after the list, so typing highlights the first value and Enter picks it.
    return (
        <>
            <DropdownMenuList>{rows}</DropdownMenuList>
            {filter.type !== PropertyFilterType.HogQL && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="filter-bar-operator-menu">
                            Operator
                            <span className="ms-auto text-muted-foreground">{operatorLabelForFilter(filter)}</span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <FilterBarOperatorRadioItems item={item} propertyType={propertyType} />
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </>
            )}
        </>
    )
}
