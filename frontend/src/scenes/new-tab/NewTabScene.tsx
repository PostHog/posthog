import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { NEW_TAB_COMMANDS, NEW_TAB_COMMANDS_ITEMS, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'

import { ProjectFileBrowser } from './components/ProjectFileBrowser'
import { Results } from './components/Results'
import { SearchInput, SearchInputCommand, SearchInputHandle } from './components/SearchInput'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

export function NewTabScene({ tabId, source }: { tabId?: string; source?: 'homepage' } = {}): JSX.Element {
    const commandInputRef = useRef<SearchInputHandle>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const pendingFocusPathRef = useRef<string | null>(null)
    const {
        search,
        newTabSceneDataInclude,
        isFileBrowserMode,
        fileBrowserBreadcrumbs,
        fileBrowserListItems,
        fileBrowserParentPath,
        projectFolderPath,
        fileBrowserHasMore,
        fileBrowserIsLoading,
        fileBrowserFirstFolderMatch,
    } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch, toggleNewTabSceneDataInclude, refreshDataAfterToggle, setProjectPath, loadMoreFileBrowser } =
        useActions(newTabSceneLogic({ tabId }))
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)

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

    const navigateToFolder = (path: string): void => {
        const trimmed = path.replace(/^\/+/, '').replace(/\/+$/, '')
        const projectUri = trimmed ? `project://${trimmed}/` : 'project://'
        setProjectPath(projectUri)
    }

    const handleSearchChange = (value: string): void => {
        if (isFileBrowserMode && value.endsWith('/') && value.length > 1) {
            const folderMatch = fileBrowserFirstFolderMatch
            if (folderMatch) {
                navigateToFolder(folderMatch.path || '')
                setSearch('')
                return
            }
        }

        if (value !== '/') {
            setSearch(value)
        }
    }

    const handleFileBrowserFolderOpen = (path: string, options?: { focusPath?: string | null }): void => {
        pendingFocusPathRef.current = options?.focusPath ?? null
        navigateToFolder(path)
    }

    useEffect(() => {
        const focusPath = pendingFocusPathRef.current
        if (!focusPath) {
            return
        }

        const match = fileBrowserListItems.find((item) => {
            const record = item.record as { path?: string } | undefined
            return record?.path === focusPath
        })

        if (match) {
            const didFocus = listboxRef.current?.focusItemByKey(match.id)
            if (didFocus) {
                pendingFocusPathRef.current = null
            }
        }
    }, [fileBrowserListItems])

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
                        <div className="flex flex-col gap-1">
                            {isFileBrowserMode ? (
                                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                                    <button
                                        type="button"
                                        className="text-primary hover:underline"
                                        onClick={() => navigateToFolder('')}
                                    >
                                        project://
                                    </button>
                                    {fileBrowserBreadcrumbs.map((crumb) => (
                                        <span className="flex items-center gap-1" key={crumb.path || crumb.label}>
                                            <span className="text-muted">/</span>
                                            <button
                                                type="button"
                                                className="text-primary hover:underline"
                                                onClick={() => navigateToFolder(crumb.path)}
                                            >
                                                {crumb.label}
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            ) : null}
                            <SearchInput
                                ref={commandInputRef}
                                commands={NEW_TAB_COMMANDS_ITEMS}
                                value={search}
                                onChange={handleSearchChange}
                                placeholder={
                                    isFileBrowserMode
                                        ? 'Filter this folder or open a subfolder…'
                                        : 'Search or ask an AI question'
                                }
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
                                            onClick={() => setIsConfigurePinnedTabsOpen(true)}
                                        >
                                            Customize homepage
                                        </ButtonPrimitive>
                                        <ConfigurePinnedTabsModal
                                            isOpen={isConfigurePinnedTabsOpen}
                                            onClose={() => setIsConfigurePinnedTabsOpen(false)}
                                        />
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
                            {isFileBrowserMode ? (
                                <ProjectFileBrowser
                                    items={fileBrowserListItems}
                                    parentPath={fileBrowserParentPath}
                                    currentPath={projectFolderPath}
                                    onOpenFolder={handleFileBrowserFolderOpen}
                                    search={search}
                                    hasMore={fileBrowserHasMore}
                                    isLoading={fileBrowserIsLoading}
                                    onLoadMore={loadMoreFileBrowser}
                                />
                            ) : (
                                <Results tabId={tabId || ''} listboxRef={listboxRef} handleAskAi={handleAskAi} />
                            )}
                        </div>
                    </div>
                </ScrollableShadows>
            </ListBox>
        </>
    )
}
