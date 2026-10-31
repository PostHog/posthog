import { useActions, useValues } from 'kea'

import { IconBookmark, IconChevronDown, IconCode, IconPlus } from '@posthog/icons'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuList,
    DropdownMenuSeparator,
    MenuEmpty,
} from '@posthog/quill'

import { canBreakDownByCategory } from './filterBarBreakdownFields'
import { FilterBarCategoryItem } from './FilterBarCategoryItem'
import { FilterBarCategoryRows } from './FilterBarCategoryRows'
import { FilterBarControlItem } from './FilterBarControlItem'
import { useFilterBarControls } from './filterBarControls'
import { FilterBarFieldItem } from './FilterBarFieldItem'
import { useFilterBarFieldPicker } from './filterBarFieldPicker'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarRecentFilterItem } from './FilterBarRecentFilterItem'
import { FilterBarSavedSetSubmenu } from './FilterBarSavedSetSubmenu'
import { FilterBarSearchRows } from './FilterBarSearchRows'
import { FilterBarCategory } from './filterBarTypes'

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
    return <FilterBarCategoryItem category={category} />
}

export function FilterBarFieldRows(): JSX.Element {
    const {
        query,
        popularFields,
        moreExpanded,
        savedSets,
        completeFilters,
        recentFilterEntries: allRecentFilterEntries,
        primaryCategories: allPrimaryCategories,
        moreCategories: allMoreCategories,
        browsingCategoryId,
        categoriesById,
    } = useValues(filterBarLogic)
    const { setMoreExpanded, startSaving } = useActions(filterBarLogic)
    const forFilter = useFilterBarFieldPicker().purpose === 'filter'
    const controls = useFilterBarControls()
    const controlsWithoutValue = forFilter ? controls.filter((control) => !control.hasValue && !control.persistent) : []
    const recentFilterEntries = forFilter ? allRecentFilterEntries : []
    const offered = (category: FilterBarCategory): boolean => forFilter || canBreakDownByCategory(category.id)
    const primaryCategories = allPrimaryCategories.filter(offered)
    const moreCategories = allMoreCategories.filter(offered)

    const browsingCategory = browsingCategoryId ? categoriesById[browsingCategoryId] : null
    if (browsingCategory) {
        return <FilterBarCategoryRows category={browsingCategory} />
    }
    if (query.trim()) {
        return <FilterBarSearchRows />
    }

    return (
        <DropdownMenuList>
            {controlsWithoutValue.length > 0 && (
                <>
                    <DropdownMenuGroup>
                        {controlsWithoutValue.map((control) => (
                            <FilterBarControlItem key={control.id} control={control} />
                        ))}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                </>
            )}
            {recentFilterEntries.length > 0 && (
                <>
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Recent</DropdownMenuLabel>
                        {recentFilterEntries.map((filter, index) => (
                            <FilterBarRecentFilterItem key={index} filter={filter} />
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
                            <FilterBarFieldItem
                                key={`${field.categoryId}/${field.key}`}
                                field={field}
                                source="popular"
                            />
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
                {!moreExpanded && (forFilter || moreCategories.length > 0) && (
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
                    {forFilter && (
                        <>
                            <DropdownMenuSeparator />
                            {/* The label lands where the More row was, so the pointer rests on nothing that opens on hover. */}
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Saved filters</DropdownMenuLabel>
                                {savedSets.map((set) => (
                                    <FilterBarSavedSetSubmenu key={set.id} set={set} />
                                ))}
                                {completeFilters.length > 0 ? (
                                    <DropdownMenuItem
                                        closeOnClick={false}
                                        onClick={startSaving}
                                        data-attr="filter-bar-save"
                                    >
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
                        </>
                    )}
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
