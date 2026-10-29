import { useActions, useValues } from 'kea'

import { DropdownMenuCheckboxItem, MenuEmpty, Spinner } from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { filterValues } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarTypedValueItem } from './FilterBarTypedValueItem'
import { FilterBarItem } from './filterBarTypes'

/** Values seen for a property, with the ticked ones first. Several can be ticked, and typed text becomes one too. */
export function FilterBarListValueItems({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { options } = useValues(propertyDefinitionsModel)
    const { toggleItemValue } = useActions(filterBarLogic)
    const selected = filterValues(item.filter).map(String)
    const typed = query.trim()
    const propertyOptions = item.filter.key ? options[item.filter.key] : undefined
    const loaded = (propertyOptions?.values ?? [])
        .map((value) => String(value.name ?? ''))
        .filter((value) => value !== '' && !selected.includes(value))
    const loading = propertyOptions?.status === 'loading'

    return (
        <>
            {typed && !selected.includes(typed) && !loaded.includes(typed) && (
                <FilterBarTypedValueItem
                    label={`Use "${typed}"`}
                    keepOpen
                    onPick={() => toggleItemValue(item.id, typed, 'list')}
                />
            )}
            {[...selected, ...loaded].map((value) => (
                <DropdownMenuCheckboxItem
                    key={value}
                    checked={selected.includes(value)}
                    onCheckedChange={() => toggleItemValue(item.id, value, 'list')}
                    data-attr="filter-bar-value"
                >
                    {value}
                </DropdownMenuCheckboxItem>
            ))}
            {loading && loaded.length === 0 && (
                <MenuEmpty>
                    <Spinner />
                    Loading values…
                </MenuEmpty>
            )}
            {!loading && loaded.length === 0 && selected.length === 0 && !typed && (
                <MenuEmpty>No values seen yet. Type one to use it.</MenuEmpty>
            )}
        </>
    )
}
