import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { NEW_TAB_COMMANDS, NEW_TAB_COMMANDS_ITEMS, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Results } from './components/Results'
import { SearchInput, SearchInputCommand, SearchInputHandle } from './components/SearchInput'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

export function NewTabScene({ tabId, source }: { tabId?: string; source?: 'homepage' } = {}): JSX.Element {
    const commandInputRef = useRef<SearchInputHandle>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const { search, newTabSceneDataInclude } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch, toggleNewTabSceneDataInclude, refreshDataAfterToggle } = useActions(newTabSceneLogic({ tabId }))
    const { showSceneDashboardChoiceModal } = useActions(
        sceneDashboardChoiceModalLogic({ scene: Scene.ProjectHomepage })
    )

    const handleAskAi = (question?: string): void => {
        const nextQuestion = (question ?? search).trim()
        router.actions.push(urls.max(undefined, nextQuestion))
    }

    // The active commands are just the items in newTabSceneDataInclude
    const activeCommands: NEW_TAB_COMMANDS[] = newTabSceneDataInclude

    // Convert active commands to selected commands for the SearchInput
    // Filter out 'all' since that represents the default state (no specific filters)
    const selectedCommands: SearchInputCommand<NEW_TAB_COMMANDS>[] = activeCommands
        .filter((commandValue) => commandValue !== 'all')
        .map((commandValue) => {
            const commandInfo = NEW_TAB_COMMANDS_ITEMS.find((cmd) => cmd.value === commandValue)
            return commandInfo || { value: commandValue, displayName: commandValue }
        })

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
                            placeholder="Search or ask an AI question"
                            activeCommands={activeCommands}
                            selectedCommands={selectedCommands}
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
                            onClearAll={() => {
                                // Clear all filters by removing all items from newTabSceneDataInclude
                                newTabSceneDataInclude.forEach((command) => {
                                    toggleNewTabSceneDataInclude(command)
                                })
                                refreshDataAfterToggle()
                            }}
                        />
                    </div>
                    <div className="border-b">
                        <div className="max-w-[1200px] mx-auto w-full px-2 @lg/main-content:px-10 pb-2">
                            <div className="flex items-center gap-x-2 gap-y-2 flex-wrap">
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
                </div>

                <ScrollableShadows
                    direction="vertical"
                    className="flex flex-col gap-4 overflow-auto h-full"
                    innerClassName="pt-4"
                    styledScrollbars
                >
                    <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-4 @lg/main-content:px-8 group/colorful-product-icons colorful-product-icons-true">
                        <div className="flex flex-col gap-2 mb-32">
                            <Results tabId={tabId || ''} listboxRef={listboxRef} handleAskAi={handleAskAi} />
                        </div>
                    </div>
                </ScrollableShadows>
            </ListBox>
        </>
    )
}
