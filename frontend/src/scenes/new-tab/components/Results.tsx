import { useActions, useValues } from 'kea'

import { IconArrowRight, IconEllipsis, IconInfo } from '@posthog/icons'
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
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { SidePanelTab } from '~/types'

import { convertToTreeDataItem, getCategoryDisplayName } from '../NewTabScene'

function Category({
    tabId,
    items,
    category,
    columnIndex,
}: {
    tabId: string
    items: NewTabTreeDataItem[]
    category: string
    columnIndex: number
}): JSX.Element {
    const typedItems = items as NewTabTreeDataItem[]
    const isFirstCategory = columnIndex === 0
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')
    const { filteredItemsGrid, search, categories, isSearching, personSearchResults } = useValues(
        newTabSceneLogic({ tabId })
    )

    return (
        <>
            <div className={cn('mb-8', { 'mb-4': newTabSceneData })} key={category}>
                <div className={cn('mb-4', { 'mb-2': newTabSceneData })}>
                    <div className={cn('flex items-baseline gap-2', { 'gap-0': newTabSceneData })}>
                        <>
                            {newTabSceneData ? (
                                <Label intent="menu" className="px-2">
                                    {getCategoryDisplayName(category)}
                                </Label>
                            ) : (
                                <h3 className="mb-0 text-lg font-medium text-secondary">
                                    {getCategoryDisplayName(category)}
                                </h3>
                            )}
                            {newTabSceneData && category === 'persons' && (
                                <div className="flex items-center gap-1">
                                    {isSearching || (isSearching && personSearchResults.length === 0) ? (
                                        <WrappingLoadingSkeleton className="h-[18px]">
                                            <LemonTag className="text-xs text-tertiary" size="small">
                                                Showing {personSearchResults.length} results
                                            </LemonTag>
                                        </WrappingLoadingSkeleton>
                                    ) : (
                                        <LemonTag className="text-xs text-tertiary" size="small">
                                            Showing {personSearchResults.length} results
                                        </LemonTag>
                                    )}
                                </div>
                            )}
                        </>
                        {category === 'recents' && isSearching && <Spinner size="small" />}
                    </div>
                    {(() => {
                        const categoryInfo = categories.find((c) => c.key === category)
                        return (
                            categoryInfo?.description && (
                                <p className="text-xs text-tertiary mt-1 mb-0 min-h-8">{categoryInfo.description}</p>
                            )
                        )
                    })()}
                </div>
                <div className="flex flex-col gap-2">
                    {category === 'recents' && typedItems.length === 0 ? (
                        // Special handling for empty project items and persons
                        <div className="flex flex-col gap-2 text-tertiary text-balance">
                            {isSearching ? (
                                <WrappingLoadingSkeleton>
                                    <ButtonPrimitive>Loading items...</ButtonPrimitive>
                                </WrappingLoadingSkeleton>
                            ) : (
                                <ButtonPrimitive inert>No results found</ButtonPrimitive>
                            )}
                        </div>
                    ) : (
                        typedItems.map((item, index) => (
                            // If we have filtered results set virtual focus to first item
                            <ButtonGroupPrimitive key={item.id} className="group w-full border-0">
                                <ContextMenu>
                                    <ContextMenuTrigger asChild>
                                        <ListBox.Item
                                            asChild
                                            focusFirst={filteredItemsGrid.length > 0 && isFirstCategory && index === 0}
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
                        ))
                    )}
                    {newTabSceneData && category === 'persons' && (
                        <ListBox.Item asChild>
                            <Link
                                to={urls.persons()}
                                buttonProps={{
                                    className: 'w-full',
                                }}
                            >
                                <IconArrowRight className="size-4" /> See all persons
                            </Link>
                        </ListBox.Item>
                    )}
                </div>
            </div>
        </>
    )
}

export function Results({ tabId }: { tabId: string }): JSX.Element {
    const {
        filteredItemsGrid,
        groupedFilteredItems,
        newTabSceneDataGroupedItems,
        search,
        selectedCategory,
        isSearching,
        newTabSceneDataIncludePersons,
    } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')

    // For newTabSceneData, use the new grouped items with section ordering
    const allCategories = newTabSceneData
        ? (() => {
              const orderedSections: string[] = []

              // Add sections in order: persons (if enabled), new, apps, data-management, recents
              if (newTabSceneDataIncludePersons) {
                  orderedSections.push('persons')
              }

              const mainSections = ['create-new', 'apps', 'data-management', 'recents']
              mainSections.forEach((section) => {
                  orderedSections.push(section)
              })

              const result = orderedSections
                  .map((section) => [section, newTabSceneDataGroupedItems[section] || []] as [string, any[]])
                  .filter(([section, items]) => {
                      // Always show persons section if filter is enabled (even when empty)
                      if (section === 'persons' && newTabSceneDataIncludePersons) {
                          return true
                      }
                      // Hide empty categories for other sections
                      return items.length > 0
                  })

              return result
          })()
        : Object.entries(groupedFilteredItems)

    if (!newTabSceneData && selectedCategory !== 'all') {
        const items = groupedFilteredItems[selectedCategory] || []
        const typedItems = items as NewTabTreeDataItem[]

        return (
            <div className="col-span-4 mb-8" key={selectedCategory}>
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
                        typedItems.map((item, index) => (
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
                        ))
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
                            <ButtonPrimitive size="sm" onClick={() => openSidePanel(SidePanelTab.Max)}>
                                Ask Max!
                            </ButtonPrimitive>
                        </ListBox.Item>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <>
            {allCategories.map(([category, items], columnIndex) => (
                <Category tabId={tabId} items={items} category={category} columnIndex={columnIndex} key={category} />
            ))}
        </>
    )
}
