import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight, IconEllipsis, IconInfo, IconSparkles } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

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
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { SidePanelTab } from '~/types'

import { convertToTreeDataItem, getCategoryDisplayName } from '../NewTabScene'
import { NoResultsFound } from './NoResultsFound'

function Category({
    tabId,
    items,
    category,
    columnIndex,
    isFirstCategoryWithResults,
}: {
    tabId: string
    items: NewTabTreeDataItem[]
    category: string
    columnIndex: number
    isFirstCategoryWithResults: boolean
}): JSX.Element {
    const typedItems = items as NewTabTreeDataItem[]
    const isFirstCategory = columnIndex === 0
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')
    const {
        filteredItemsGrid,
        search,
        isSearching,
        newTabSceneDataGroupedItemsFullData,
        getSectionItemLimit,
        newTabSceneDataInclude,
    } = useValues(newTabSceneLogic({ tabId }))
    const { showMoreInSection } = useActions(newTabSceneLogic({ tabId }))

    return (
        <>
            <div
                className={cn('mb-8', {
                    'mb-0 @xl/main-content:flex @xl/main-content:flex-row @xl/main-content:gap-x-4': newTabSceneData,
                })}
                key={category}
            >
                <div className={cn('mb-4', { 'mb-2 @xl/main-content:min-w-[200px]': newTabSceneData })}>
                    <div className={cn('flex items-baseline gap-2', { 'gap-0': newTabSceneData })}>
                        {newTabSceneData ? (
                            <Label intent="menu" className="px-2">
                                {getCategoryDisplayName(category)}
                            </Label>
                        ) : (
                            <h3 className="mb-0 text-lg font-medium text-secondary">
                                {getCategoryDisplayName(category)}
                            </h3>
                        )}
                        {category === 'recents' && isSearching && <Spinner size="small" />}
                        {/* Show "No results found" tag for other categories when empty and include is NOT 'all' */}
                        {newTabSceneData &&
                            !['persons', 'eventDefinitions', 'propertyDefinitions'].includes(category) &&
                            typedItems.length === 0 &&
                            !newTabSceneDataInclude.includes('all') && (
                                <LemonTag className="text-xs text-tertiary" size="small">
                                    No results found
                                </LemonTag>
                            )}
                    </div>
                </div>
                <div
                    className={cn('flex flex-col gap-2', {
                        '@xl/main-content:grow min-w-0 empty:hidden gap-1': newTabSceneData,
                    })}
                >
                    {typedItems.length === 0 ? (
                        // Show loading for recents when searching, otherwise show nothing (tag shows in header)
                        category === 'recents' && isSearching ? (
                            <div className="flex flex-col gap-2 text-tertiary text-balance">
                                <WrappingLoadingSkeleton>
                                    <ButtonPrimitive size="sm">Loading items...</ButtonPrimitive>
                                </WrappingLoadingSkeleton>
                            </div>
                        ) : null
                    ) : (
                        typedItems.map((item, index) => {
                            const focusFirst =
                                (newTabSceneData && isFirstCategoryWithResults && index === 0) ||
                                (filteredItemsGrid.length > 0 && isFirstCategory && index === 0)

                            return (
                                // If we have filtered results set virtual focus to first item
                                <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                    <ContextMenu>
                                        <ContextMenuTrigger asChild>
                                            <ListBox.Item
                                                asChild
                                                focusFirst={focusFirst}
                                                row={index}
                                                column={columnIndex}
                                            >
                                                <Link
                                                    to={item.href || '#'}
                                                    className="w-full"
                                                    buttonProps={{
                                                        size: 'sm',
                                                        hasSideActionRight: true,
                                                        className:
                                                            'data-[focused=true]:outline-2 data-[focused=true]:outline-accent',
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
                    {newTabSceneData && (
                        <>
                            {(() => {
                                const currentLimit = getSectionItemLimit(category)
                                const fullCount = newTabSceneDataGroupedItemsFullData[category] || 0
                                const hasMore = fullCount > currentLimit

                                return (
                                    hasMore && (
                                        <ListBox.Item asChild>
                                            <ButtonPrimitive
                                                size="sm"
                                                onClick={() => showMoreInSection(category)}
                                                className="w-full text-tertiary data-[focused=true]:outline-2 data-[focused=true]:outline-accent data-[focused=true]:text-primary"
                                            >
                                                <IconArrowRight className="rotate-90" /> Show all (
                                                {fullCount - currentLimit} more)
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                    )
                                )
                            })()}
                            {category === 'persons' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.persons()}
                                        buttonProps={{
                                            size: 'sm',
                                            className:
                                                'w-full text-tertiary data-[focused=true]:outline-2 data-[focused=true]:outline-accent data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconArrowRight /> See all persons
                                    </Link>
                                </ListBox.Item>
                            )}
                            {category === 'eventDefinitions' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.eventDefinitions()}
                                        buttonProps={{
                                            size: 'sm',
                                            className:
                                                'w-full text-tertiary data-[focused=true]:outline-2 data-[focused=true]:outline-accent data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconArrowRight /> See all events
                                    </Link>
                                </ListBox.Item>
                            )}
                            {category === 'propertyDefinitions' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.propertyDefinitions()}
                                        buttonProps={{
                                            size: 'sm',
                                            className:
                                                'w-full text-tertiary data-[focused=true]:outline-2 data-[focused=true]:outline-accent data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconArrowRight /> See all properties
                                    </Link>
                                </ListBox.Item>
                            )}
                        </>
                    )}
                </div>
            </div>
            {newTabSceneData && <div className="h-px w-full bg-border-primary" />}
        </>
    )
}

export function Results({
    tabId,
    searchInputRef,
    listboxRef,
    handleAskAi,
}: {
    tabId: string
    searchInputRef: React.RefObject<HTMLInputElement>
    listboxRef: React.RefObject<ListBoxHandle>
    handleAskAi: (question?: string) => void
}): JSX.Element {
    const {
        filteredItemsGrid,
        groupedFilteredItems,
        search,
        selectedCategory,
        isSearching,
        newTabSceneDataInclude,
        allCategories,
        firstCategoryWithResults,
    } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')
    const items = groupedFilteredItems[selectedCategory] || []
    const typedItems = items as NewTabTreeDataItem[]

    // Track whether we have any results
    const hasResults = allCategories.some(([, items]) => items.length > 0)

    // Check if we should show NoResultsFound component
    // (include='all' + search term + no results + flag on)
    const shouldShowGlobalNoResults =
        newTabSceneData && newTabSceneDataInclude.includes('all') && search.trim() !== '' && !hasResults && !isSearching

    // Focus first item when search is complete and we have results
    useEffect(() => {
        if (newTabSceneData && !isSearching && hasResults && firstCategoryWithResults) {
            listboxRef.current?.focusFirstItem()
        }
    }, [newTabSceneData, isSearching, hasResults, firstCategoryWithResults, listboxRef])

    if (!newTabSceneData && selectedCategory !== 'all') {
        return (
            <div className="col-span-full mb-8" key={selectedCategory}>
                <div className="mb-4">
                    <div className="flex items-baseline gap-2">
                        <h3 className="mb-0 text-lg font-medium text-secondary">
                            {getCategoryDisplayName(selectedCategory)}
                        </h3>
                        {selectedCategory === 'recents' && isSearching && <Spinner size="small" />}
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    {selectedCategory === 'recents' && typedItems.length === 0 ? (
                        // Special handling for empty project items and persons
                        <div className="flex flex-col gap-2 text-tertiary text-balance">
                            {isSearching ? 'Searching...' : 'No results found'}
                        </div>
                    ) : (
                        typedItems.map((item, index) => {
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
                                                        size: 'sm',
                                                        hasSideActionRight: true,
                                                        truncate: true,
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
                </div>
            </div>
        )
    }

    return (
        <>
            {allCategories.map(([category, items]: [string, NewTabTreeDataItem[]], columnIndex: number) => (
                <Category
                    tabId={tabId}
                    items={items}
                    category={category}
                    columnIndex={columnIndex}
                    isFirstCategoryWithResults={category === firstCategoryWithResults}
                    key={category}
                />
            ))}

            {/* Show NoResultsFound when include='all' + search term + no results */}
            {shouldShowGlobalNoResults && <NoResultsFound handleAskAi={handleAskAi} />}

            {/* Show "No results found" when there's a search term but no results */}
            {!newTabSceneData && filteredItemsGrid.length === 0 && !isSearching ? (
                <div className="flex flex-col gap-4 px-2 py-2 bg-glass-bg-3000 rounded-lg col-span-full">
                    <div className="flex flex-col gap-1">
                        <p className="text-tertiary mb-1">
                            <IconInfo /> No results found
                        </p>
                        <div className="flex gap-1 items-center">
                            <ListBox.Item asChild>
                                <ButtonPrimitive
                                    size="sm"
                                    onClick={() => {
                                        setSearch('')
                                        searchInputRef.current?.focus()
                                    }}
                                    variant="panel"
                                    className="list-none data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                                >
                                    Clear search
                                </ButtonPrimitive>
                            </ListBox.Item>
                            or{' '}
                            <ListBox.Item asChild>
                                <ButtonPrimitive
                                    size="sm"
                                    onClick={() => openSidePanel(SidePanelTab.Max)}
                                    variant="panel"
                                    className="data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                                >
                                    <IconSparkles />
                                    Ask Posthog AI
                                </ButtonPrimitive>
                            </ListBox.Item>
                        </div>
                    </div>
                </div>
            ) : null}
        </>
    )
}
