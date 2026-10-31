import { useValues } from 'kea'

import { DropdownMenuGroup, DropdownMenuLabel, DropdownMenuList, MenuEmpty, Spinner } from '@posthog/quill'

import { canBreakDownByCategory } from './filterBarBreakdownFields'
import { FilterBarControlItem } from './FilterBarControlItem'
import { useFilterBarControls } from './filterBarControls'
import { FilterBarFieldItem } from './FilterBarFieldItem'
import { useFilterBarFieldPicker } from './filterBarFieldPicker'
import { fieldFromFilter, filterValues } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarRecentFilterItem } from './FilterBarRecentFilterItem'
import { FilterBarCategoryId, FilterBarField } from './filterBarTypes'

/** What the query matched: recent filters by field or value, then the fields each category knows, grouped. */
export function FilterBarSearchRows(): JSX.Element {
    const { query, searchResults, searchResultsLoading, recentFilterEntries, categoriesById } =
        useValues(filterBarLogic)
    const forFilter = useFilterBarFieldPicker().purpose === 'filter'
    const needle = query.trim().toLowerCase()
    const matchingRecents = recentFilterEntries.filter((filter) => {
        if (!forFilter) {
            return false
        }
        const field = fieldFromFilter(filter)
        return field && `${field.label} ${filterValues(filter).join(' ')}`.toLowerCase().includes(needle)
    })
    const matchingControls = useFilterBarControls().filter(
        (control) =>
            forFilter && !control.hasValue && !control.persistent && control.label.toLowerCase().includes(needle)
    )
    const resultEntries = (Object.entries(searchResults) as [FilterBarCategoryId, FilterBarField[]][]).filter(
        ([categoryId]) => forFilter || canBreakDownByCategory(categoryId)
    )
    const nothingFound =
        !searchResultsLoading &&
        resultEntries.length === 0 &&
        matchingRecents.length === 0 &&
        matchingControls.length === 0

    return (
        <DropdownMenuList>
            {matchingControls.length > 0 && (
                <DropdownMenuGroup>
                    {matchingControls.map((control) => (
                        <FilterBarControlItem key={control.id} control={control} />
                    ))}
                </DropdownMenuGroup>
            )}
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
