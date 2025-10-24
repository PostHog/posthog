import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef, useState } from 'react'

import {
    IconApps,
    IconDatabase,
    IconDocument,
    IconInfo,
    IconPerson,
    IconPlusSmall,
    IconSearch,
    IconSparkles,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import {
    NEW_TAB_CATEGORY_ITEMS,
    NEW_TAB_COMMANDS,
    NEW_TAB_COMMANDS_ITEMS,
    newTabSceneLogic,
} from 'scenes/new-tab/newTabSceneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'

import { Results } from './components/Results'
import { SearchHints } from './components/SearchHints'
import { SearchInput, SearchInputCommand, SearchInputHandle } from './components/SearchInput'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

export function NewTabScene({ tabId, source }: { tabId?: string; source?: 'homepage' } = {}): JSX.Element {
    const commandInputRef = useRef<SearchInputHandle>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const {
        filteredItemsGrid,
        search,
        categories,
        selectedCategory,
        newTabSceneDataIncludePersons,
        newTabSceneDataIncludeEventDefinitions,
        newTabSceneDataIncludePropertyDefinitions,
        newTabSceneDataInclude,
        isSearching,
    } = useValues(newTabSceneLogic({ tabId }))
    const { mobileLayout } = useValues(navigationLogic)
    const { setSearch, setSelectedCategory, toggleNewTabSceneDataInclude, refreshDataAfterToggle } = useActions(
        newTabSceneLogic({ tabId })
    )
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )
    const newTabSceneData = useFeatureFlag('DATA_IN_NEW_TAB_SCENE')
    const isAIAvailable = useFeatureFlag('ARTIFICIAL_HOG')
    const showAiFeature = newTabSceneData && isAIAvailable

    // State for selected commands (tags)
    const [selectedCommands, setSelectedCommands] = useState<SearchInputCommand<NEW_TAB_COMMANDS>[]>([])

    const focusSearchInput = (): void => {
        commandInputRef.current?.focus()
    }

    const handleAskAi = (question?: string): void => {
        const nextQuestion = (question ?? search).trim()
        router.actions.push(urls.max(undefined, nextQuestion))
    }

    // Determine active commands based on current state
    const activeCommands: NEW_TAB_COMMANDS[] = []
    if (newTabSceneDataInclude.length > 0) {
        activeCommands.push(...newTabSceneDataInclude)
    }
    if (newTabSceneDataIncludePersons) {
        activeCommands.push('persons')
    }
    if (newTabSceneDataIncludeEventDefinitions) {
        activeCommands.push('eventDefinitions')
    }
    if (newTabSceneDataIncludePropertyDefinitions) {
        activeCommands.push('propertyDefinitions')
    }

    return (
        <>
            <ListBox
                ref={listboxRef}
                className="w-full grid grid-rows-[auto_1fr] flex-col h-[calc(100vh-var(--scene-layout-header-height))]"
                virtualFocus
                autoSelectFirst
            >
                <div className="sr-only">
                    <p>
                        Welcome to the new tab, type / to see commands... or type a search term, you can navigate all
                        interactive elements with the keyboard
                    </p>
                </div>
                <div className="flex flex-col gap-2">
                    <div className="px-2 @lg/main-content:px-8 pt-2 @lg/main-content:pt-8 mx-auto w-full max-w-[1200px] ">
                        {!newTabSceneData ? (
                            <LemonInput
                                inputRef={inputRef}
                                value={search}
                                onChange={(value) => setSearch(value)}
                                prefix={<IconSearch />}
                                className="w-full"
                                placeholder="Search..."
                                autoFocus
                                allowClear
                                aria-controls="combobox-listbox"
                                aria-label="Search for a person, event, property, or app, you can navigate all interactive elements with the keyboard"
                            />
                        ) : (
                            <SearchInput
                                ref={commandInputRef}
                                commands={NEW_TAB_COMMANDS_ITEMS}
                                value={search}
                                onChange={(value) => {
                                    // Only prevent setting search if the entire value is just "/" (command mode)
                                    // Allow "/" characters in other positions for normal search
                                    if (value !== '/') {
                                        setSearch(value)
                                    }
                                }}
                                placeholder="Search or type / to see commands..."
                                activeCommands={activeCommands}
                                selectedCommands={selectedCommands}
                                onSelectedCommandsChange={(commands) =>
                                    setSelectedCommands(commands as SearchInputCommand<NEW_TAB_COMMANDS>[])
                                }
                                onCommandSelect={(command) => {
                                    if (command.value === 'all') {
                                        // Check if "all" is currently selected
                                        if (newTabSceneDataInclude.includes('all')) {
                                            // If "all" is on, turn off everything (clear all filters)
                                            newTabSceneDataInclude.forEach((selectedCommand) => {
                                                toggleNewTabSceneDataInclude(selectedCommand)
                                            })
                                        } else {
                                            // If "all" is off, turn it on (which will show all filters)
                                            toggleNewTabSceneDataInclude('all')
                                        }
                                    } else {
                                        toggleNewTabSceneDataInclude(command.value as NEW_TAB_COMMANDS)
                                    }
                                    // Refresh data after toggle
                                    refreshDataAfterToggle()
                                }}
                            />
                        )}

                        <div
                            className={cn('mx-1.5', {
                                'mt-[.5px]': newTabSceneData,
                            })}
                        >
                            <SearchHints
                                filteredItemsGridLength={filteredItemsGrid.length}
                                focusSearchInput={focusSearchInput}
                                tabId={tabId || ''}
                                handleAskAi={handleAskAi}
                            />
                        </div>
                    </div>
                    {!newTabSceneData ? (
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
                                                    focusSearchInput()
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
                    ) : (
                        <div className="border-b">
                            <div className="max-w-[1200px] mx-auto w-full px-2 @lg/main-content:px-10 pb-2">
                                <div className="flex items-center gap-x-2 gap-y-2 flex-wrap">
                                    {newTabSceneDataInclude.length === 0 ||
                                    newTabSceneDataInclude.includes('all') ? null : (
                                        <>
                                            <span className="text-xs text-tertiary">Showing only:</span>
                                            {newTabSceneDataInclude
                                                .filter((command) => command !== 'all')
                                                .map((command) => {
                                                    const commandInfo = NEW_TAB_COMMANDS_ITEMS.find(
                                                        (cmd) => cmd.value === command
                                                    )
                                                    if (!commandInfo) {
                                                        return null
                                                    }

                                                    return (
                                                        <ListBox.Item asChild key={command}>
                                                            <ButtonPrimitive
                                                                size="xxs"
                                                                variant="outline"
                                                                onClick={() => {
                                                                    toggleNewTabSceneDataInclude(command)
                                                                    refreshDataAfterToggle()
                                                                    focusSearchInput()
                                                                }}
                                                                className="text-xs data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                                                                tooltip={
                                                                    <span>
                                                                        Remove{' '}
                                                                        <span className="font-bold">
                                                                            {commandInfo.displayName}
                                                                        </span>{' '}
                                                                        from selected filters
                                                                    </span>
                                                                }
                                                            >
                                                                {command === 'persons' && (
                                                                    <IconPerson className="size-4" />
                                                                )}
                                                                {command === 'eventDefinitions' && (
                                                                    <IconApps className="size-4" />
                                                                )}
                                                                {command === 'propertyDefinitions' && (
                                                                    <IconApps className="size-4" />
                                                                )}
                                                                {command === 'create-new' && (
                                                                    <IconPlusSmall className="size-4" />
                                                                )}
                                                                {command === 'apps' && <IconApps className="size-4" />}
                                                                {command === 'data-management' && (
                                                                    <IconDatabase className="size-4" />
                                                                )}
                                                                {command === 'recents' && (
                                                                    <IconDocument className="size-4" />
                                                                )}
                                                                {command === 'askAI' && showAiFeature && (
                                                                    <IconSparkles className="size-4" />
                                                                )}
                                                                {commandInfo.displayName}
                                                                <IconX className="size-3" />
                                                            </ButtonPrimitive>
                                                        </ListBox.Item>
                                                    )
                                                })}
                                            {newTabSceneDataInclude.length > 1 && (
                                                <ListBox.Item asChild>
                                                    <ButtonPrimitive
                                                        size="xxs"
                                                        variant="panel"
                                                        onClick={() => {
                                                            // Clear all filters
                                                            newTabSceneDataInclude.forEach((command) => {
                                                                toggleNewTabSceneDataInclude(command)
                                                            })
                                                            refreshDataAfterToggle()
                                                            focusSearchInput()
                                                        }}
                                                        className="text-xs data-[focused=true]:outline-2 data-[focused=true]:outline-accent"
                                                        tooltip="Clear all filters"
                                                    >
                                                        <IconX className="size-4" />
                                                        Clear all
                                                    </ButtonPrimitive>
                                                </ListBox.Item>
                                            )}
                                        </>
                                    )}

                                    {source === 'homepage' ? (
                                        <>
                                            <ButtonPrimitive
                                                size="xxs"
                                                data-attr="project-home-customize-homepage"
                                                className="ml-auto text-xs"
                                                onClick={showSceneDashboardChoiceModal}
                                            >
                                                Customize homepage
                                            </ButtonPrimitive>
                                            <SceneDashboardChoiceModal scene={Scene.ProjectHomepage} />
                                        </>
                                    ) : null}
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                <ScrollableShadows
                    direction="vertical"
                    className="flex flex-col gap-4 overflow-auto h-full"
                    innerClassName={cn('pt-6', { 'pt-4': newTabSceneData })}
                    styledScrollbars
                >
                    <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-4 @lg/main-content:px-8 group/colorful-product-icons colorful-product-icons-true">
                        {!newTabSceneData && filteredItemsGrid.length === 0 && !isSearching ? (
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
                                            <ButtonPrimitive size="sm" onClick={() => handleAskAi()} variant="panel">
                                                Ask Posthog AI
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div
                                className={cn({
                                    'grid grid-cols-1 @md/main-content:grid-cols-2 @xl/main-content:grid-cols-3 @2xl/main-content:grid-cols-4 gap-4':
                                        !newTabSceneData,
                                    'flex flex-col gap-2 mb-32': newTabSceneData,
                                })}
                            >
                                {/* TODO: Remove this once we're done testing */}
                                {newTabSceneData && (
                                    <div className="col-span-full border border-primary border-px rounded-md p-2">
                                        <p className="flex flex-col items-center @md/main-content:flex-row gap-1 m-0 text-sm text-tertiary">
                                            <IconInfo className="size-4 text-accent" /> You're trying out the new tab UX
                                            with the flag:{' '}
                                            <span className="font-mono border border-primary border-px rounded-md px-1 mb-0">
                                                data-in-new-tab-scene
                                            </span>
                                        </p>
                                    </div>
                                )}
                                <Results
                                    tabId={tabId || ''}
                                    searchInputRef={commandInputRef.current?.getInputRef() || { current: null }}
                                    listboxRef={listboxRef}
                                    handleAskAi={handleAskAi}
                                />
                            </div>
                        )}
                    </div>
                </ScrollableShadows>
            </ListBox>
        </>
    )
}
