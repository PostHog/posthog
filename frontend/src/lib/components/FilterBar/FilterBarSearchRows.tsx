import { useValues } from 'kea'

import { DropdownMenuGroup, DropdownMenuLabel, DropdownMenuList, MenuEmpty, Spinner } from '@posthog/quill'

import { FilterBarFieldItem } from './FilterBarFieldItem'
import { fieldFromFilter, valueLabelForFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarRecentFilterItem } from './FilterBarRecentFilterItem'
import { FilterBarCategoryId, FilterBarField } from './filterBarTypes'

/** What the query matched: recent filters by field or value, then the fields each category knows, grouped. */
export function FilterBarSearchRows(): JSX.Element {
    const { query, searchResults, searchResultsLoading, recentFilterEntries, categoriesById } =
        useValues(filterBarLogic)
    const needle = query.trim().toLowerCase()
    const matchingRecents = recentFilterEntries.filter((filter) => {
        const field = fieldFromFilter(filter)
        return field && `${field.label} ${valueLabelForFilter(filter).text}`.toLowerCase().includes(needle)
    })
    const resultEntries = Object.entries(searchResults) as [FilterBarCategoryId, FilterBarField[]][]
    const nothingFound = !searchResultsLoading && resultEntries.length === 0 && matchingRecents.length === 0

    return (
        <DropdownMenuList>
            {matchingRecents.length > 0 && (
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Recent</DropdownMenuLabel>
                    {matchingRecents.map((filter, index) => (
                        <FilterBarRecentFilterItem key={index} filter={filter} />
                    ))}
                </DropdownMenuGroup>
            )}
            {resultEntries.map(([categoryId, fields]) => (
                <DropdownMenuGroup key={categoryId}>
                    <DropdownMenuLabel>{categoriesById[categoryId]?.label ?? categoryId}</DropdownMenuLabel>
                    {fields.map((field) => (
                        <FilterBarFieldItem key={field.key} field={field} source="search" />
                    ))}
                </DropdownMenuGroup>
            ))}
            {searchResultsLoading && resultEntries.length === 0 && (
                <MenuEmpty>
                    <Spinner />
                    Searching…
                </MenuEmpty>
            )}
            {nothingFound && <MenuEmpty>No field matches "{query.trim()}"</MenuEmpty>}
        </DropdownMenuList>
    )
}
