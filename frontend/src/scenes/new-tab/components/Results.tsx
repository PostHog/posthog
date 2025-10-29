import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useEffect, useRef } from 'react'

import { IconArrowRight, IconEllipsis, IconExternal, IconInfo, IconSparkles } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
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
import { ListBox, ListBoxGroupHandle, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { urls } from 'scenes/urls'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { groupsModel } from '~/models/groupsModel'
import { SidePanelTab } from '~/types'

import { NoResultsFound } from './NoResultsFound'

export const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        'create-new': 'Create new',
        apps: 'Apps',
        'data-management': 'Data management',
        recents: 'Recents',
        persons: 'Persons',
        groups: 'Groups',
        eventDefinitions: 'Events',
        propertyDefinitions: 'Properties',
        askAI: 'Posthog AI',
    }
    return displayNames[category] || category
}
export const formatRelativeTimeShort = (date: string | number | Date | Dayjs | null | undefined): string => {
    if (!date) {
        return ''
    }

    const parsedDate = dayjs(date)

    if (!parsedDate.isValid()) {
        return ''
    }

    const now = dayjs()
    const seconds = Math.max(0, now.diff(parsedDate, 'second'))

    if (seconds < 60) {
        return 'just now'
    }

    const minutes = now.diff(parsedDate, 'minute')

    if (minutes < 60) {
        return `${minutes} min ago`
    }

    const hours = now.diff(parsedDate, 'hour')

    if (hours < 24) {
        return `${hours} hr${hours === 1 ? '' : 's'} ago`
    }

    const days = now.diff(parsedDate, 'day')

    if (days < 30) {
        return `${days} day${days === 1 ? '' : 's'} ago`
    }

    const months = now.diff(parsedDate, 'month') || 1

    if (months < 12) {
        return `${months} mo${months === 1 ? '' : 's'} ago`
    }

    const years = now.diff(parsedDate, 'year') || 1

    return `${years} yr${years === 1 ? '' : 's'} ago`
}

// Helper function to convert NewTabTreeDataItem to TreeDataItem for menu usage
export function convertToTreeDataItem(item: NewTabTreeDataItem): TreeDataItem {
    return {
        ...item,
        record: {
            ...item.record,
            href: item.href,
            path: item.name, // Use name as path for menu compatibility
        },
    }
}

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
    const groupRef = useRef<ListBoxGroupHandle>(null)
    const pendingFocusIndexRef = useRef<number | null>(null)
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
        recents,
        recentsLoading,
    } = useValues(newTabSceneLogic({ tabId }))
    const { showMoreInSection, logCreateNewItem, loadMoreRecents } = useActions(newTabSceneLogic({ tabId }))
    const { groupTypes } = useValues(groupsModel)
    const previousRecentsLoadingRef = useRef(recentsLoading)

    // Make sure the same index remains focused after clicking "load more"
    useEffect(() => {
        const wasLoading = previousRecentsLoadingRef.current
        previousRecentsLoadingRef.current = recentsLoading

        if (category !== 'recents') {
            pendingFocusIndexRef.current = null
            return
        }

        if (wasLoading && !recentsLoading && pendingFocusIndexRef.current !== null) {
            const indexToFocus = pendingFocusIndexRef.current
            pendingFocusIndexRef.current = null

            const restoreFocus = (): void => {
                const focused = groupRef.current?.resumeFocus(indexToFocus)
                if (!focused) {
                    setTimeout(() => {
                        groupRef.current?.resumeFocus(indexToFocus)
                    }, 50)
                }
            }

            if (typeof requestAnimationFrame === 'function') {
                requestAnimationFrame(restoreFocus)
            } else {
                setTimeout(restoreFocus, 0)
            }
        }
    }, [category, recentsLoading])

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
                            !['persons', 'groups', 'eventDefinitions', 'propertyDefinitions'].includes(category) &&
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
                        <ListBox.Group ref={groupRef} groupId={`category-${category}`}>
                            {typedItems.map((item, index) => {
                                const isCreateNew = item.category === 'create-new'
                                const focusFirst =
                                    (newTabSceneData && isFirstCategoryWithResults && index === 0) ||
                                    (filteredItemsGrid.length > 0 && isFirstCategory && index === 0)

                                const lastViewedAt =
                                    item.lastViewedAt ??
                                    (item.record as { last_viewed_at?: string | null } | undefined)?.last_viewed_at ??
                                    null

                                const record = item.record as
                                    | ({
                                          groupNoun?: string
                                          groupDisplayName?: string
                                      } & Record<string, any>)
                                    | undefined

                                const groupNoun =
                                    item.category === 'groups' ? record?.groupNoun || item.name.split(':')[0] : null
                                const groupDisplayName =
                                    item.category === 'groups'
                                        ? typeof item.displayName === 'string'
                                            ? item.displayName
                                            : item.name.split(':').slice(1).join(':').trim()
                                        : null

                                const highlightText = (text: string): ReactNode =>
                                    search ? <SearchHighlightMultiple string={text} substring={search} /> : text

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
                                                    focusKey={item.id}
                                                    index={index}
                                                >
                                                    <Link
                                                        to={item.href || '#'}
                                                        className="w-full"
                                                        buttonProps={{
                                                            size: 'sm',
                                                            hasSideActionRight: true,
                                                        }}
                                                        onClick={(e) => {
                                                            e.preventDefault()
                                                            if (item.href) {
                                                                if (isCreateNew) {
                                                                    logCreateNewItem(item.href)
                                                                }
                                                                router.actions.push(item.href)
                                                            }
                                                        }}
                                                    >
                                                        <span className="text-sm">{item.icon ?? item.name[0]}</span>
                                                        <span className="flex min-w-0 items-center gap-2">
                                                            {groupNoun ? (
                                                                <>
                                                                    <span className="text-sm truncate text-primary">
                                                                        {highlightText(
                                                                            groupDisplayName &&
                                                                                groupDisplayName.length > 0
                                                                                ? groupDisplayName
                                                                                : item.name
                                                                        )}
                                                                    </span>
                                                                    <LemonTag
                                                                        size="small"
                                                                        type="muted"
                                                                        className="shrink-0"
                                                                    >
                                                                        {highlightText(
                                                                            capitalizeFirstLetter(groupNoun.trim())
                                                                        )}
                                                                    </LemonTag>
                                                                </>
                                                            ) : (
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
                                                            )}
                                                            {lastViewedAt ? (
                                                                <span className="text-xs text-muted whitespace-nowrap">
                                                                    {formatRelativeTimeShort(lastViewedAt)}
                                                                </span>
                                                            ) : null}
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
                                            <DropdownMenuContent
                                                loop
                                                align="end"
                                                side="bottom"
                                                className="max-w-[250px]"
                                            >
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
                            })}
                            {newTabSceneData &&
                                (() => {
                                    const currentLimit = getSectionItemLimit(category)
                                    const fullCount = newTabSceneDataGroupedItemsFullData[category] || 0
                                    const isRecentsSection = category === 'recents'
                                    const hasMore = isRecentsSection
                                        ? recents.hasMore || fullCount > currentLimit
                                        : fullCount > currentLimit

                                    return (
                                        hasMore && (
                                            <ListBox.Item
                                                asChild
                                                focusKey={`show-all-${category}`}
                                                index={typedItems.length} // This button is at the end of the group
                                            >
                                                <ButtonPrimitive
                                                    size="sm"
                                                    disabled={isRecentsSection && recentsLoading}
                                                    onClick={() => {
                                                        const showAllIndex = typedItems.length // The "Show all" button index

                                                        if (isRecentsSection) {
                                                            pendingFocusIndexRef.current = showAllIndex
                                                            loadMoreRecents()
                                                        } else {
                                                            showMoreInSection(category)
                                                            setTimeout(() => {
                                                                groupRef.current?.resumeFocus(showAllIndex)
                                                            }, 0)
                                                        }
                                                    }}
                                                    className="w-full text-tertiary data-[focused=true]:text-primary"
                                                >
                                                    <IconArrowRight className="rotate-90" />
                                                    {isRecentsSection
                                                        ? ' Load more...'
                                                        : ` Show all (${fullCount - currentLimit} more)`}
                                                </ButtonPrimitive>
                                            </ListBox.Item>
                                        )
                                    )
                                })()}
                        </ListBox.Group>
                    )}
                    {newTabSceneData && (
                        <>
                            {category === 'persons' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.persons()}
                                        buttonProps={{
                                            size: 'sm',
                                            className: 'w-full text-tertiary data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconExternal /> See all persons
                                    </Link>
                                </ListBox.Item>
                            )}
                            {category === 'eventDefinitions' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.eventDefinitions()}
                                        buttonProps={{
                                            size: 'sm',
                                            className: 'w-full text-tertiary data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconExternal /> See all events
                                    </Link>
                                </ListBox.Item>
                            )}
                            {category === 'groups' && groupTypes.size > 0 && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.groups(Array.from(groupTypes.keys())[0])}
                                        buttonProps={{
                                            size: 'sm',
                                            className: 'w-full text-tertiary data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconExternal /> See all groups
                                    </Link>
                                </ListBox.Item>
                            )}
                            {category === 'propertyDefinitions' && (
                                <ListBox.Item asChild>
                                    <Link
                                        to={urls.propertyDefinitions()}
                                        buttonProps={{
                                            size: 'sm',
                                            className: 'w-full text-tertiary data-[focused=true]:text-primary',
                                        }}
                                    >
                                        <IconExternal /> See all properties
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
    const { setSearch, logCreateNewItem } = useActions(newTabSceneLogic({ tabId }))
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
                            const isCreateNew = item.category === 'create-new'
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
                                                focusKey={item.id}
                                            >
                                                <Link
                                                    to={item.href || '#'}
                                                    className="w-full"
                                                    buttonProps={{
                                                        size: 'sm',
                                                        hasSideActionRight: true,
                                                        truncate: true,
                                                    }}
                                                    onClick={(e) => {
                                                        e.preventDefault()
                                                        if (item.href) {
                                                            if (isCreateNew) {
                                                                logCreateNewItem(item.href)
                                                            }
                                                            router.actions.push(item.href)
                                                        }
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
                                    className="list-none"
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
