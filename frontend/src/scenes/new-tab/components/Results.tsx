import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconEllipsis, IconInfo } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { convertToTreeDataItem, getCategoryDisplayName } from '../NewTabScene'

const MAX_VISIBLE_ITEMS = 5

function Category({
    items,
    category,
    columnIndex,
    meta,
    isFlagged,
    filteredItemsGridLength,
    search,
    isLoading,
    showPersonsFooter,
    personResultsCount = 0,
    isExpanded,
    onToggle,
    maxVisibleItems,
    onAskMax,
}: {
    items: NewTabTreeDataItem[]
    category: string
    columnIndex: number
    meta?: { label: string; description?: string }
    isFlagged: boolean
    filteredItemsGridLength: number
    search: string
    isLoading: boolean
    showPersonsFooter?: boolean
    personResultsCount?: number
    isExpanded: boolean
    onToggle: () => void
    maxVisibleItems: number
    onAskMax: (question: string) => void
}): JSX.Element {
    const typedItems = items as NewTabTreeDataItem[]
    const isFirstCategory = columnIndex === 0
    const displayName = meta?.label || getCategoryDisplayName(category)
    const description = meta?.description
    const visibleItems = isExpanded ? typedItems : typedItems.slice(0, maxVisibleItems)
    const hasMoreItems = typedItems.length > maxVisibleItems

    return (
        <div className={cn('mb-8', { 'mb-2': isFlagged })}>
            <div className="flex flex-col gap-3 @lg/main-content:grid @lg/main-content:grid-cols-[minmax(160px,1fr)_minmax(0,3fr)] @lg/main-content:gap-6 @lg/main-content:items-start">
                <div className="flex flex-col gap-2">
                    <div className="flex items-baseline gap-2">
                        {isFlagged ? (
                            <Label intent="menu" className="px-2">
                                {displayName}
                            </Label>
                        ) : (
                            <h3 className="mb-0 text-lg font-medium text-secondary">{displayName}</h3>
                        )}
                        {isFlagged && category === 'persons://' && personResultsCount > 0 && (
                            <span className="text-xs text-tertiary">Showing first {personResultsCount} entries</span>
                        )}
                        {isLoading && <Spinner size="small" />}
                    </div>
                    {description ? <p className="text-xs text-tertiary mt-1 mb-0 min-h-8">{description}</p> : null}
                </div>
                <div className="flex flex-col gap-0.25 w-full">
                    {(category === 'recents' || isFlagged) && typedItems.length === 0 ? (
                        <div className="flex flex-col gap-2 text-tertiary text-balance">
                            {isLoading ? (
                                <WrappingLoadingSkeleton>
                                    <ButtonPrimitive>Loading items...</ButtonPrimitive>
                                </WrappingLoadingSkeleton>
                            ) : (
                                <ButtonPrimitive inert>No results found</ButtonPrimitive>
                            )}
                        </div>
                    ) : (
                        visibleItems.map((item, index) => {
                            const isAskItem = item.protocol === 'ask://'
                            const question = typeof item.record?.question === 'string' ? item.record.question : search
                            const displayValue = item.displayName || item.name || question || 'Ask Max'

                            if (isAskItem) {
                                return (
                                    <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                        <ListBox.Item
                                            asChild
                                            focusFirst={filteredItemsGridLength > 0 && isFirstCategory && index === 0}
                                            row={index}
                                            column={columnIndex}
                                        >
                                            <Link
                                                to="#"
                                                className="w-full"
                                                onClick={(event) => {
                                                    event.preventDefault()
                                                    onAskMax(question ?? '')
                                                }}
                                                buttonProps={{
                                                    size: 'base',
                                                }}
                                            >
                                                <span className="text-sm">{item.icon ?? displayValue[0]}</span>
                                                <span className="text-sm truncate text-primary">
                                                    {displayValue || 'Ask Max'}
                                                </span>
                                            </Link>
                                        </ListBox.Item>
                                    </ButtonGroupPrimitive>
                                )
                            }

                            return (
                                <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                    <ContextMenu>
                                        <ContextMenuTrigger asChild>
                                            <ListBox.Item
                                                asChild
                                                focusFirst={
                                                    filteredItemsGridLength > 0 && isFirstCategory && index === 0
                                                }
                                                row={index}
                                                column={columnIndex}
                                            >
                                                <Link
                                                    to={item.href || '#'}
                                                    className="w-full"
                                                    buttonProps={{
                                                        size: 'base',
                                                        hasSideActionRight: true,
                                                    }}
                                                >
                                                    <span className="text-sm">{item.icon ?? item.name[0]}</span>
                                                    <span className="text-sm truncate text-primary">
                                                        {search ? (
                                                            <SearchHighlightMultiple
                                                                string={item.name}
                                                                substring={search}
                                                            />
                                                        ) : (
                                                            item.displayName || item.name
                                                        )}
                                                    </span>
                                                </Link>
                                            </ListBox.Item>
                                        </ContextMenuTrigger>
                                        <ContextMenuContent loop className="max-w-[250px]">
                                            <ContextMenuGroup>
                                                <MenuItems
                                                    item={convertToTreeDataItem(item)}
                                                    type="context"
                                                    root="project://"
                                                    onlyTree={false}
                                                    showSelectMenuOption={false}
                                                />
                                            </ContextMenuGroup>
                                        </ContextMenuContent>
                                    </ContextMenu>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <ButtonPrimitive
                                                size="xs"
                                                iconOnly
                                                isSideActionRight
                                                className="opacity-0 group-hover:opacity-100 group-has-[button[data-state=open]]:opacity-100 mt-px"
                                            >
                                                <IconEllipsis className="size-3" />
                                            </ButtonPrimitive>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                                            <DropdownMenuGroup>
                                                <MenuItems
                                                    item={convertToTreeDataItem(item)}
                                                    type="dropdown"
                                                    root="project://"
                                                    onlyTree={false}
                                                    showSelectMenuOption={false}
                                                />
                                            </DropdownMenuGroup>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </ButtonGroupPrimitive>
                            )
                        })
                    )}
                    {hasMoreItems && (
                        <div className="mt-2">
                            <ButtonPrimitive size="sm" type="button" onClick={onToggle}>
                                {isExpanded ? 'Show less' : 'Show more...'}
                            </ButtonPrimitive>
                        </div>
                    )}
                    {isFlagged && category === 'persons://' && showPersonsFooter && (
                        <ListBox.Item asChild>
                            <Link
                                to={urls.persons()}
                                buttonProps={{
                                    className: 'w-full mt-2',
                                }}
                            >
                                <IconArrowRight className="size-4" /> See all persons
                            </Link>
                        </ListBox.Item>
                    )}
                </div>
            </div>
            {isFlagged && (
                <div className="px-4">
                    <SceneDivider />
                </div>
            )}
        </div>
    )
}

export function Results({ tabId, onAskMax }: { tabId: string; onAskMax: (question: string) => void }): JSX.Element {
    const {
        filteredItemsGrid,
        groupedFilteredItems,
        search,
        categories,
        selectedCategory,
        isSearching,
        destinationSections,
        destinationOptionMap,
        personSearchResults,
        recentsLoading,
        personSearchResultsLoading,
    } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')

    const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>({})

    useEffect(() => {
        setExpandedCategories({})
    }, [search])

    const isCategoryExpanded = (category: string): boolean => !!expandedCategories[category]
    const toggleCategoryExpansion = (category: string): void => {
        setExpandedCategories((current) => ({ ...current, [category]: !current[category] }))
    }

    const flaggedLoadingByCategory: Record<string, boolean> = {
        'project://': recentsLoading,
        'persons://': personSearchResultsLoading,
    }

    const allCategories = newTabSceneData ? destinationSections : Object.entries(groupedFilteredItems)

    if (!newTabSceneData && selectedCategory !== 'all') {
        const items = groupedFilteredItems[selectedCategory] || []
        const typedItems = items as NewTabTreeDataItem[]
        const isExpanded = isCategoryExpanded(selectedCategory)
        const visibleItems = isExpanded ? typedItems : typedItems.slice(0, MAX_VISIBLE_ITEMS)
        const hasMoreItems = typedItems.length > MAX_VISIBLE_ITEMS

        return (
            <div className="col-span-4 mb-8" key={selectedCategory}>
                <div className="mb-4">
                    <div className="flex items-baseline gap-2">
                        <h3 className="mb-0 text-lg font-medium text-secondary">
                            {getCategoryDisplayName(selectedCategory)}
                        </h3>
                        {selectedCategory === 'recents' && isSearching && <Spinner size="small" />}
                    </div>
                    {(() => {
                        const categoryInfo = categories.find((c) => c.key === selectedCategory)
                        return (
                            categoryInfo?.description && (
                                <p className="text-xs text-tertiary mt-1 mb-0 min-h-8">{categoryInfo.description}</p>
                            )
                        )
                    })()}
                </div>
                <div className="flex flex-col gap-0.25">
                    {selectedCategory === 'recents' && typedItems.length === 0 ? (
                        // Special handling for empty project items and persons
                        <div className="flex flex-col gap-2 text-tertiary text-balance">
                            {isSearching ? 'Searching...' : 'No results found'}
                        </div>
                    ) : (
                        visibleItems.map((item, index) => {
                            const isAskItem = item.protocol === 'ask://'
                            const question = typeof item.record?.question === 'string' ? item.record.question : search
                            const displayValue = item.displayName || item.name || question || 'Ask Max'

                            if (isAskItem) {
                                return (
                                    <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                        <ListBox.Item
                                            asChild
                                            focusFirst={filteredItemsGrid.length > 0 && index === 0}
                                            row={index}
                                            column={0}
                                        >
                                            <Link
                                                to="#"
                                                className="w-full"
                                                onClick={(event) => {
                                                    event.preventDefault()
                                                    onAskMax(question ?? '')
                                                }}
                                                buttonProps={{ size: 'base' }}
                                            >
                                                <span className="text-sm">{item.icon ?? displayValue[0]}</span>
                                                <span className="text-sm truncate text-primary">
                                                    {displayValue || 'Ask Max'}
                                                </span>
                                            </Link>
                                        </ListBox.Item>
                                    </ButtonGroupPrimitive>
                                )
                            }

                            return (
                                // If we have filtered results set virtual focus to first item
                                <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                    <ContextMenu>
                                        <ContextMenuTrigger asChild>
                                            <ListBox.Item
                                                asChild
                                                focusFirst={filteredItemsGrid.length > 0 && index === 0}
                                                row={index}
                                                column={0}
                                            >
                                                <Link
                                                    to={item.href || '#'}
                                                    className="w-full"
                                                    buttonProps={{
                                                        size: 'base',
                                                        hasSideActionRight: true,
                                                    }}
                                                >
                                                    <span className="text-sm">{item.icon ?? item.name[0]}</span>
                                                    <span className="text-sm truncate text-primary">
                                                        {search ? (
                                                            <SearchHighlightMultiple
                                                                string={item.name}
                                                                substring={search}
                                                            />
                                                        ) : (
                                                            item.displayName || item.name
                                                        )}
                                                    </span>
                                                </Link>
                                            </ListBox.Item>
                                        </ContextMenuTrigger>
                                        <ContextMenuContent loop className="max-w-[250px]">
                                            <ContextMenuGroup>
                                                <MenuItems
                                                    item={convertToTreeDataItem(item)}
                                                    type="context"
                                                    root="project://"
                                                    onlyTree={false}
                                                    showSelectMenuOption={false}
                                                />
                                            </ContextMenuGroup>
                                        </ContextMenuContent>
                                    </ContextMenu>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <ButtonPrimitive
                                                size="xs"
                                                iconOnly
                                                isSideActionRight
                                                className="opacity-0 group-hover:opacity-100 group-has-[button[data-state=open]]:opacity-100 mt-px"
                                            >
                                                <IconEllipsis className="size-3" />
                                            </ButtonPrimitive>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                                            <DropdownMenuGroup>
                                                <MenuItems
                                                    item={convertToTreeDataItem(item)}
                                                    type="dropdown"
                                                    root="project://"
                                                    onlyTree={false}
                                                    showSelectMenuOption={false}
                                                />
                                            </DropdownMenuGroup>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </ButtonGroupPrimitive>
                            )
                        })
                    )}
                    {hasMoreItems && (
                        <div className="mt-2">
                            <ButtonPrimitive
                                size="sm"
                                type="button"
                                onClick={() => toggleCategoryExpansion(selectedCategory)}
                            >
                                {isExpanded ? 'Show less' : 'Show more...'}
                            </ButtonPrimitive>
                        </div>
                    )}
                </div>
            </div>
        )
    }

    // Show "No results found" for non-flagged version when no results and not searching
    if (!newTabSceneData && filteredItemsGrid.length === 0 && !isSearching) {
        return (
            <div className="flex flex-col gap-4 px-2 py-2 bg-glass-bg-3000 rounded-lg">
                <div className="flex flex-col gap-1">
                    <p className="text-tertiary mb-2">
                        <IconInfo /> No results found
                    </p>
                    <div className="flex gap-1">
                        <ListBox.Item asChild className="list-none">
                            <ButtonPrimitive size="sm" onClick={() => setSearch('')}>
                                Clear search
                            </ButtonPrimitive>{' '}
                        </ListBox.Item>
                        or{' '}
                        <ListBox.Item asChild>
                            <ButtonPrimitive size="sm" onClick={() => onAskMax(search)}>
                                Ask Max!
                            </ButtonPrimitive>
                        </ListBox.Item>
                    </div>
                </div>
            </div>
        )
    }

    const personResultsCount = personSearchResults.length

    return (
        <>
            {allCategories.map(([category, items], columnIndex) => (
                <Category
                    items={items as NewTabTreeDataItem[]}
                    category={category}
                    columnIndex={columnIndex}
                    key={category}
                    meta={newTabSceneData ? destinationOptionMap[category] : categories.find((c) => c.key === category)}
                    isFlagged={!!newTabSceneData}
                    filteredItemsGridLength={filteredItemsGrid.length}
                    search={search}
                    isLoading={
                        newTabSceneData
                            ? (flaggedLoadingByCategory[category] ?? false)
                            : category === 'recents' && isSearching
                    }
                    showPersonsFooter={!!newTabSceneData && category === 'persons://' && personResultsCount > 0}
                    personResultsCount={personResultsCount}
                    isExpanded={isCategoryExpanded(category)}
                    onToggle={() => toggleCategoryExpansion(category)}
                    maxVisibleItems={MAX_VISIBLE_ITEMS}
                    onAskMax={onAskMax}
                />
            ))}
        </>
    )
}
