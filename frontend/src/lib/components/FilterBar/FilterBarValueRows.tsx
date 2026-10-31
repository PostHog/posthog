import { useActions, useValues } from 'kea'

import { DropdownMenuCheckboxItem, DropdownMenuList, MenuEmpty } from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { categoryIdForFilter } from './filterBarCategories'
import { FilterBarCohortValueItems } from './FilterBarCohortValueItems'
import { FilterBarDateValueItems } from './FilterBarDateValueItems'
import {
    filterValues,
    groupTypeIndexForCategory,
    propertyDefinitionTypeForCategory,
    valueKindForFilter,
} from './filterBarFields'
import { FilterBarListValueItems } from './FilterBarListValueItems'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarNumberValueItems } from './FilterBarNumberValueItems'
import { FilterBarItem } from './filterBarTypes'

/**
 * The value picker for one filter: the values for its kind. The menu's search field doubles as the place to type a
 * value the list does not offer. The operator is set from the chip's own operator segment.
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

    return <DropdownMenuList>{rows}</DropdownMenuList>
}
