import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconEllipsis, IconSearch, IconSidePanel } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
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
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import { maxLogic } from 'scenes/max/maxLogic'
import { NEW_TAB_CATEGORY_ITEMS, NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { SidePanelTab } from '~/types'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        'create-new': 'Create new',
        apps: 'Apps',
        'data-management': 'Data management',
        recents: 'Recents',
    }
    return displayNames[category] || category
}

// Helper function to convert NewTabTreeDataItem to TreeDataItem for menu usage
function convertToTreeDataItem(item: NewTabTreeDataItem): TreeDataItem {
    return {
        ...item,
        record: {
            ...item.record,
            href: item.href,
            path: item.name, // Use name as path for menu compatibility
        },
    }
}

export function NewTabScene({ tabId, source }: { tabId?: string; source?: 'homepage' } = {}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const { filteredItemsGrid, groupedFilteredItems, search, selectedItem, categories, selectedCategory, isSearching } =
        useValues(newTabSceneLogic({ tabId }))
    const { mobileLayout } = useValues(navigationLogic)
    const { setQuestion, focusInput } = useActions(maxLogic)
    const { setSearch, setSelectedCategory } = useActions(newTabSceneLogic({ tabId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )

    // scroll it to view
    useEffect(() => {
        if (selectedItem) {
            const element = document.querySelector('.selected-new-tab-item')
            element?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
        }
    }, [selectedItem])

    return (
        <ListBox
            ref={listboxRef}
            className="w-full grid grid-rows-[auto_1fr] flex-col h-[calc(100vh-var(--scene-layout-header-height))]"
            virtualFocus
            autoSelectFirst
        >
            <div className="flex flex-col gap-4">
                <div className="px-1 @lg/main-content:px-8 pt-2 @lg/main-content:pt-8 mx-auto w-full max-w-[1200px] ">
                    <ListBox.Item asChild virtualFocusIgnore>
                        <LemonInput
                            inputRef={inputRef}
                            value={search}
                            onChange={(value) => setSearch(value)}
                            prefix={<IconSearch />}
                            className="w-full"
                            placeholder="Search..."
                            autoFocus
                            allowClear
                        />
                    </ListBox.Item>
                    <div className="mx-1.5">
                        <div className="flex justify-between items-center relative text-xs font-medium overflow-hidden py-1 px-1.5 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]">
                            <span>
                                <span className="text-tertiary">Try:</span>
                                <ListBox.Item asChild>
                                    <ButtonPrimitive
                                        size="xxs"
                                        className="text-xs"
                                        onClick={() => setSearch('New SQL query')}
                                    >
                                        New SQL query
                                    </ButtonPrimitive>
                                </ListBox.Item>
                                <span className="text-tertiary">or</span>
                                <ListBox.Item asChild>
                                    <ButtonPrimitive
                                        size="xxs"
                                        className="text-xs"
                                        onClick={() => setSearch('Experiment')}
                                    >
                                        Experiment
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            </span>
                            <span className="text-primary flex gap-1 items-center">
                                {/* if filtered results lenght is 0, this will be the first to focus */}
                                <ListBox.Item asChild focusFirst={filteredItemsGrid.length === 0}>
                                    <ButtonPrimitive
                                        size="xxs"
                                        onClick={() => {
                                            openSidePanel(SidePanelTab.Max)
                                            setSearch('')
                                            setQuestion(search)
                                            focusInput()
                                        }}
                                        className="text-xs"
                                        tooltip="Hit enter to open Max!"
                                    >
                                        Ask Max!
                                        <IconSidePanel />
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            </span>
                        </div>
                    </div>
                </div>
                <TabsPrimitive
                    value={selectedCategory}
                    onValueChange={(value) => setSelectedCategory(value as NEW_TAB_CATEGORY_ITEMS)}
                >
                    <TabsPrimitiveList className="border-b">
                        <div className="max-w-[1200px] mx-auto w-full px-1 @lg/main-content:px-8 flex">
                            {categories.map((category) => (
                                <TabsPrimitiveTrigger
                                    value={category.key}
                                    className="px-2 py-1 cursor-pointer"
                                    key={category.key}
                                    onClick={() => {
                                        if (!mobileLayout) {
                                            // If not mobile, we want to re-focus the input if we trigger the tabs (which filter)
                                            inputRef.current?.focus()
                                            // Reset listbox focus on first item
                                            listboxRef.current?.focusFirstItem()
                                        }
                                    }}
                                >
                                    {category.label}
                                </TabsPrimitiveTrigger>
                            ))}
                            {source === 'homepage' ? (
                                <>
                                    <LemonButton
                                        type="tertiary"
                                        size="small"
                                        data-attr="project-home-customize-homepage"
                                        className="ml-auto"
                                        onClick={showSceneDashboardChoiceModal}
                                    >
                                        Customize homepage
                                    </LemonButton>
                                    <SceneDashboardChoiceModal scene={Scene.ProjectHomepage} />
                                </>
                            ) : null}
                        </div>
                    </TabsPrimitiveList>
                </TabsPrimitive>
            </div>

            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-4 overflow-auto h-full"
                innerClassName="pt-6"
                styledScrollbars
            >
                <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-3 @lg/main-content:px-8">
                    {filteredItemsGrid.length === 0 ? (
                        <div className="flex flex-col gap-4">
                            {selectedCategory === 'recents' ? (
                                <div className="flex flex-col gap-2 text-center py-8">
                                    <h3 className="text-lg font-medium text-muted">Search for project items</h3>
                                    <p className="text-muted">
                                        Try searching for cohorts, actions, experiments, dashboards, and more...
                                    </p>
                                </div>
                            ) : (
                                <div className="flex gap-1 items-center">
                                    No results found,{' '}
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
                            )}
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 @md/main-content:grid-cols-2 @xl/main-content:grid-cols-3 @2xl/main-content:grid-cols-4 gap-4 group/colorful-product-icons colorful-product-icons-true">
                            {Object.entries(groupedFilteredItems).map(([category, items], columnIndex) => {
                                const typedItems = items as NewTabTreeDataItem[]
                                const isFirstCategory = columnIndex === 0
                                return (
                                    <div
                                        className={cn('mb-8', {
                                            'col-span-4': selectedCategory !== 'all',
                                        })}
                                        key={category}
                                    >
                                        <div className="mb-4">
                                            <div className="flex items-center gap-2">
                                                <h3 className="mb-0 text-lg font-medium text-muted">
                                                    {search ? (
                                                        <SearchHighlightMultiple
                                                            string={getCategoryDisplayName(category)}
                                                            substring={search}
                                                        />
                                                    ) : (
                                                        getCategoryDisplayName(category)
                                                    )}
                                                </h3>
                                                {category === 'recents' && isSearching && <Spinner size="small" />}
                                            </div>
                                        </div>
                                        <div className="flex flex-col gap-2">
                                            {category === 'recents' && typedItems.length === 0 ? (
                                                // Special handling for empty project items
                                                <div className="flex flex-col gap-2 text-tertiary text-balance">
                                                    {isSearching ? 'Searching...' : 'No results found'}
                                                </div>
                                            ) : (
                                                typedItems.map((item, index) => (
                                                    // If we have filtered results set virtual focus to first item
                                                    <ButtonGroupPrimitive className="group w-full border-0">
                                                        <ContextMenu>
                                                            <ContextMenuTrigger asChild>
                                                                <ListBox.Item
                                                                    key={item.id}
                                                                    asChild
                                                                    focusFirst={
                                                                        filteredItemsGrid.length > 0 &&
                                                                        isFirstCategory &&
                                                                        index === 0
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
                                                                        <span className="text-sm">
                                                                            {item.icon ?? item.name[0]}
                                                                        </span>
                                                                        <span className="text-sm truncate text-primary">
                                                                            {search ? (
                                                                                <SearchHighlightMultiple
                                                                                    string={item.name}
                                                                                    substring={search}
                                                                                />
                                                                            ) : (
                                                                                item.name
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
                                                ))
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            </ScrollableShadows>
        </ListBox>
    )
}
