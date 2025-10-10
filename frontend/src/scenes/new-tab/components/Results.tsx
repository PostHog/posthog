import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
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
import { cn } from 'lib/utils/css-classes'
import { NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

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
    const newTabLogic = newTabSceneLogic({ tabId })
    const { filteredItemsGrid, search, categories, isSearching, personSearchPagination, personSearchResults } =
        useValues(newTabSceneLogic({ tabId }))

    return (
        <>
            <div className={cn('mb-8', { 'mb-2': newTabSceneData })} key={category}>
                <div className="mb-4">
                    <div className="flex items-baseline gap-2">
                        {newTabSceneData ? (
                            <Label intent="menu" className="px-2">
                                {getCategoryDisplayName(category)}
                            </Label>
                        ) : (
                            <>
                                <h3 className="mb-0 text-lg font-medium text-secondary">
                                    {getCategoryDisplayName(category)}
                                </h3>
                                {newTabSceneData && category === 'persons' && personSearchResults.length > 0 && (
                                    <span className="text-xs text-tertiary">
                                        Showing first {personSearchResults.length} entries
                                    </span>
                                )}
                            </>
                        )}
                        {(category === 'recents' || (newTabSceneData && category === 'persons')) && isSearching && (
                            <Spinner size="small" />
                        )}
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
                    {(category === 'recents' || newTabSceneData) && typedItems.length === 0 ? (
                        // Special handling for empty project items and persons
                        <div className="flex flex-col gap-2 text-tertiary text-balance px-2">
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
                    {newTabSceneData && category === 'persons' && personSearchPagination.hasMore && (
                        <ListBox.Item asChild>
                            <ButtonPrimitive
                                variant="panel"
                                onClick={() => {
                                    const searchTerm = search.startsWith('/persons ')
                                        ? search.replace('/persons ', '')
                                        : search
                                    newTabLogic.actions.loadMorePersonSearchResults({
                                        searchTerm,
                                    })
                                }}
                                className="w-full mt-2"
                            >
                                Load more persons
                            </ButtonPrimitive>
                        </ListBox.Item>
                    )}
                </div>
            </div>
            {newTabSceneData && (
                <div className="px-4">
                    <SceneDivider />
                </div>
            )}
        </>
    )
}

export function Results({ tabId }: { tabId: string }): JSX.Element {
    const {
        filteredItemsGrid,
        groupedFilteredItems,
        newTabSceneDataGroupedItems,
        search,
        categories,
        selectedCategory,
        isSearching,
        newTabSceneDataIncludePersons,
    } = useValues(newTabSceneLogic({ tabId }))
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
                      // For other sections, only show if they have items
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
                    {(() => {
                        const categoryInfo = categories.find((c) => c.key === selectedCategory)
                        return (
                            categoryInfo?.description && (
                                <p className="text-xs text-tertiary mt-1 mb-0 min-h-8">{categoryInfo.description}</p>
                            )
                        )
                    })()}
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

    return (
        <>
            {allCategories.map(([category, items], columnIndex) => (
                <Category tabId={tabId} items={items} category={category} columnIndex={columnIndex} key={category} />
            ))}
        </>
    )
}
