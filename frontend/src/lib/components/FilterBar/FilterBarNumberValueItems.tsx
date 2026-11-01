import { useActions, useValues } from 'kea'

import { DropdownMenuCheckboxItem, MenuEmpty } from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { filterValues } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarTypedValueItem } from './FilterBarTypedValueItem'
import { FilterBarItem } from './filterBarTypes'

const SUGGESTIONS_SHOWN = 10

/** One number, typed in the search field or picked from the values seen for the property. */
export function FilterBarNumberValueItems({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { options } = useValues(propertyDefinitionsModel)
    const { toggleItemValue } = useActions(filterBarLogic)
    const selected = filterValues(item.filter).map(String)
    const typed = query.trim()
    const number = Number(typed)
    const suggestions = (options[item.filter.key ?? '']?.values ?? [])
        .map((value) => String(value.name ?? ''))
        .filter((value) => value !== '' && Number.isFinite(Number(value)))
        .slice(0, SUGGESTIONS_SHOWN)

    return (
        <>
            {!typed && <MenuEmpty>Type a number</MenuEmpty>}
            {typed && !Number.isFinite(number) && <MenuEmpty>"{typed}" is not a number</MenuEmpty>}
            {typed && Number.isFinite(number) && (
                <FilterBarTypedValueItem
                    label={`Use ${number}`}
                    keepOpen={false}
                    onPick={() => toggleItemValue(item.id, number, 'number')}
                />
            )}
            {suggestions.map((value) => (
                <DropdownMenuCheckboxItem
                    key={value}
                    checked={selected.includes(value)}
                    closeOnClick
                    onCheckedChange={() => toggleItemValue(item.id, Number(value), 'number')}
                    data-attr="filter-bar-value"
                >
                    {value}
                </DropdownMenuCheckboxItem>
            ))}
        </>
    )
}
