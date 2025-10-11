import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconInfo, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { maxLogic } from 'scenes/max/maxLogic'
import { NEW_TAB_CATEGORY_ITEMS, NewTabTreeDataItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SidePanelTab } from '~/types'

import { Results } from './components/Results'
import { SearchHints } from './components/SearchHints'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

export const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        'create-new': 'Create new',
        apps: 'Apps',
        'data-management': 'Data management',
        recents: 'Recents',
        persons: 'Persons',
    }
    return displayNames[category] || category
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

export function NewTabScene({ tabId, source }: { tabId?: string; source?: 'homepage' } = {}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const { filteredItemsGrid, search, selectedItem, categories, selectedCategory, specialSearchMode } = useValues(
        newTabSceneLogic({ tabId })
    )
    const { mobileLayout } = useValues(navigationLogic)
    const { setQuestion, focusInput: focusMaxInput } = useActions(maxLogic)
    const { setSearch, setSelectedCategory } = useActions(newTabSceneLogic({ tabId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')

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
                        <SearchHints
                            specialSearchMode={specialSearchMode}
                            search={search}
                            filteredItemsGridLength={filteredItemsGrid.length}
                            setSearch={setSearch}
                            setQuestion={setQuestion}
                            focusMaxInput={focusMaxInput}
                            focusSearchInput={() => inputRef.current?.focus()}
                            openSidePanel={openSidePanel}
                        />
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
                                    {newTabSceneData && category.key === 'persons' ? '*' : null}
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
                <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-4 @lg/main-content:px-8">
                    {filteredItemsGrid.length === 0 ? (
                        <div className="flex flex-col gap-4 px-2 py-2 bg-glass-bg-3000 rounded-lg">
                            <div className="flex flex-col gap-1">
                                <p className="text-tertiary mb-2">
                                    <IconInfo /> No results found
                                </p>
                                <div className="flex gap-1">
                                    <ListBox.Item asChild className="list-none">
                                        <ButtonPrimitive size="sm" onClick={() => setSearch('')} variant="panel">
                                            Clear search
                                        </ButtonPrimitive>{' '}
                                    </ListBox.Item>
                                    or{' '}
                                    <ListBox.Item asChild>
                                        <ButtonPrimitive
                                            size="sm"
                                            onClick={() => openSidePanel(SidePanelTab.Max)}
                                            variant="panel"
                                        >
                                            Ask Max!
                                        </ButtonPrimitive>
                                    </ListBox.Item>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 @md/main-content:grid-cols-2 @xl/main-content:grid-cols-3 @2xl/main-content:grid-cols-4 gap-4 group/colorful-product-icons colorful-product-icons-true">
                            <Results tabId={tabId || ''} />
                        </div>
                    )}
                </div>
            </ScrollableShadows>
        </ListBox>
    )
}
