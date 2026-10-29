import { useActions, useValues } from 'kea'

import { IconBookmark, IconChevronDown, IconCode, IconPlus } from '@posthog/icons'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuList,
    DropdownMenuSeparator,
    MenuEmpty,
    Spinner,
} from '@posthog/quill'

import { AnyPropertyFilter } from '~/types'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { FilterBarCategorySubmenu } from './FilterBarCategorySubmenu'
import { fieldFromFilter, operatorLabelForFilter, valueLabelForFilter } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarSavedSetSubmenu } from './FilterBarSavedSetSubmenu'
import { FilterBarCategory, FilterBarField } from './filterBarTypes'

/** A recent filter reads as a sentence, "Browser is Chrome", so one click applies it whole. */
function RecentFilterItem({ filter }: { filter: AnyPropertyFilter }): JSX.Element | null {
    const { addFilter } = useActions(filterBarLogic)
    const field = fieldFromFilter(filter)
    if (!field) {
        return null
    }
    const value = valueLabelForFilter(filter)
    return (
        <DropdownMenuItem onClick={() => addFilter(filter, 'recent')} data-attr="filter-bar-recent">
            <FilterBarCategoryIcon categoryId={field.categoryId} />
            <span className="truncate">{field.label}</span>
            <span className="truncate text-muted-foreground">
                {operatorLabelForFilter(filter)} {value.text}
            </span>
        </DropdownMenuItem>
    )
}

function FieldItem({ field, source }: { field: FilterBarField; source: 'popular' | 'search' }): JSX.Element {
    const { addField } = useActions(filterBarLogic)
    return (
        <DropdownMenuItem
            closeOnClick={false}
            onClick={() => addField(field, source)}
            data-attr={`filter-bar-field-${source}`}
        >
            <FilterBarCategoryIcon categoryId={field.categoryId} />
            <span className="truncate">{field.label}</span>
        </DropdownMenuItem>
    )
}

function CategoryRow({ category }: { category: FilterBarCategory }): JSX.Element {
    const { openSqlDialog } = useActions(filterBarLogic)
    if (category.id === 'sql') {
        return (
            <DropdownMenuItem onClick={() => openSqlDialog(null)} data-attr="filter-bar-category-sql">
                <IconCode />
                SQL expression…
            </DropdownMenuItem>
        )
    }
    return <FilterBarCategorySubmenu category={category} />
}

/** The first screen of the picker: what the person used lately, what most people use, then everything by category. */
export function FilterBarFieldRows(): JSX.Element {
    const {
        query,
        searchResults,
        searchResultsLoading,
        recentFilterEntries,
        popularFields,
        primaryCategories,
        moreCategories,
        moreExpanded,
        categoriesById,
        savedSets,
        completeFilters,
    } = useValues(filterBarLogic)
    const { setMoreExpanded, startSaving } = useActions(filterBarLogic)

    if (query.trim()) {
        const needle = query.trim().toLowerCase()
        const matchingRecents = recentFilterEntries.filter((filter) => {
            const field = fieldFromFilter(filter)
            return field && `${field.label} ${valueLabelForFilter(filter).text}`.toLowerCase().includes(needle)
        })
        const resultEntries = Object.entries(searchResults) as [FilterBarCategory['id'], FilterBarField[]][]
        const nothingFound = !searchResultsLoading && resultEntries.length === 0 && matchingRecents.length === 0
        return (
            <DropdownMenuList>
                {matchingRecents.length > 0 && (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Recent</DropdownMenuLabel>
                        {matchingRecents.map((filter, index) => (
                            <RecentFilterItem key={index} filter={filter} />
                        ))}
                    </DropdownMenuGroup>
                )}
                {resultEntries.map(([categoryId, fields]) => (
                    <DropdownMenuGroup key={categoryId}>
                        <DropdownMenuLabel>{categoriesById[categoryId]?.label ?? categoryId}</DropdownMenuLabel>
                        {fields.map((field) => (
                            <FieldItem key={field.key} field={field} source="search" />
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

    return (
        <DropdownMenuList>
            {recentFilterEntries.length > 0 && (
                <>
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Recent</DropdownMenuLabel>
                        {recentFilterEntries.map((filter, index) => (
                            <RecentFilterItem key={index} filter={filter} />
                        ))}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                </>
            )}
            {popularFields.length > 0 && (
                <>
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Popular</DropdownMenuLabel>
                        {popularFields.map((field) => (
                            <FieldItem key={`${field.categoryId}/${field.key}`} field={field} source="popular" />
                        ))}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                </>
            )}
            <DropdownMenuGroup>
                <DropdownMenuLabel>Browse</DropdownMenuLabel>
                {primaryCategories.map((category) => (
                    <CategoryRow key={category.id} category={category} />
                ))}
                {!moreExpanded && (
                    <DropdownMenuItem
                        closeOnClick={false}
                        onClick={() => setMoreExpanded(true)}
                        data-attr="filter-bar-more"
                    >
                        <IconChevronDown />
                        More
                    </DropdownMenuItem>
                )}
            </DropdownMenuGroup>
            {moreExpanded && (
                <>
                    <DropdownMenuSeparator />
                    {/* The label lands where the More row was, so the pointer rests on nothing that opens on hover. */}
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Saved filters</DropdownMenuLabel>
                        {savedSets.map((set) => (
                            <FilterBarSavedSetSubmenu key={set.id} set={set} />
                        ))}
                        {completeFilters.length > 0 ? (
                            <DropdownMenuItem closeOnClick={false} onClick={startSaving} data-attr="filter-bar-save">
                                <IconPlus />
                                Save current filters…
                            </DropdownMenuItem>
                        ) : (
                            savedSets.length === 0 && (
                                <MenuEmpty>
                                    <IconBookmark />
                                    Add a filter, then save it here
                                </MenuEmpty>
                            )
                        )}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>More</DropdownMenuLabel>
                        {moreCategories.map((category) => (
                            <CategoryRow key={category.id} category={category} />
                        ))}
                    </DropdownMenuGroup>
                </>
            )}
        </DropdownMenuList>
    )
}
