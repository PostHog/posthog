import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { DropdownMenuCheckboxItem, DropdownMenuSeparator, MenuEmpty, Spinner } from '@posthog/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { filterValues } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarTypedValueItem } from './FilterBarTypedValueItem'
import { FilterBarItem } from './filterBarTypes'

/**
 * Values seen for a property. The values ticked when the menu opened sit on top, above a separator. A value ticked
 * while the menu is open stays where it is, so the row under the pointer never jumps; it moves up on the next open.
 */
export function FilterBarListValueItems({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { options } = useValues(propertyDefinitionsModel)
    const { toggleItemValue } = useActions(filterBarLogic)
    const selected = filterValues(item.filter).map(String)
    // The menu mounts this list each time it opens, so the first render's selection is the one to pin.
    const [pinned] = useState(() => selected)
    const typed = query.trim()
    const needle = typed.toLowerCase()
    const propertyOptions = item.filter.key ? options[item.filter.key] : undefined
    const loaded = (propertyOptions?.values ?? [])
        .map((value) => String(value.name ?? ''))
        .filter((value) => value !== '')
    const loading = propertyOptions?.status === 'loading'

    const top = pinned.filter((value) => value.toLowerCase().includes(needle))
    // Values typed in while open are ticked but absent from the loaded list, so they lead the lower group.
    const rest = [
        ...selected.filter((value) => !pinned.includes(value) && !loaded.includes(value)),
        ...loaded.filter((value) => !pinned.includes(value)),
    ]

    const valueRow = (value: string): JSX.Element => (
        <DropdownMenuCheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={() => toggleItemValue(item.id, value, 'list')}
            data-attr="filter-bar-value"
        >
            {value}
        </DropdownMenuCheckboxItem>
    )

    return (
        <>
            {typed && !selected.includes(typed) && !loaded.includes(typed) && (
                <FilterBarTypedValueItem
                    label={`Use "${typed}"`}
                    keepOpen
                    onPick={() => toggleItemValue(item.id, typed, 'list')}
                />
            )}
            {top.map(valueRow)}
            {top.length > 0 && rest.length > 0 && <DropdownMenuSeparator />}
            {rest.map(valueRow)}
            {loading && rest.length === 0 && (
                <MenuEmpty>
                    <Spinner />
                    Loading values…
                </MenuEmpty>
            )}
            {!loading && rest.length === 0 && top.length === 0 && !typed && (
                <MenuEmpty>No values seen yet. Type one to use it.</MenuEmpty>
            )}
        </>
    )
}
