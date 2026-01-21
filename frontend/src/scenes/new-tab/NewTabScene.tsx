import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

import { Search } from 'lib/components/Search/Search'
import { SearchItem } from 'lib/components/Search/searchLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import {
    NEW_TAB_COMMANDS,
    NEW_TAB_COMMANDS_ITEMS,
    getNewTabProjectTreeLogicProps,
    newTabSceneLogic,
} from 'scenes/new-tab/newTabSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Results } from './components/Results'
import { SearchInput, SearchInputBreadcrumb, SearchInputCommand, SearchInputHandle } from './components/SearchInput'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

export function NewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const isNewSearchUx = useFeatureFlag('NEW_SEARCH_UX')

    if (isNewSearchUx) {
        return <NewSearchTabScene />
    }

    return <DefaultNewTabScene tabId={tabId} />
}

function NewSearchTabScene(): JSX.Element {
    const handleItemSelect = useCallback((item: SearchItem) => {
        if (item.href) {
            router.actions.push(item.href)
        }
    }, [])

    return (
        <Search.Root
            logicKey="new-tab"
            isActive
            onItemSelect={handleItemSelect}
            showAskAiLink
            className="size-full grow"
        >
            <div className="sticky top-0 w-full max-w-[640px] mx-auto">
                <Search.Input autoFocus className="pt-8" />
                <Search.Status />
            </div>
            <Search.Separator className="-mx-4" />
            <Search.Results
                className="w-full mx-auto grow overflow-y-auto"
                listClassName="max-w-[640px] mx-auto"
                groupLabelClassName="bg-(--scene-layout-background)"
            />
        </Search.Root>
    )
}

function DefaultNewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const commandInputRef = useRef<SearchInputHandle>(null)
    const listboxRef = useRef<ListBoxHandle>(null)
    const {
        search,
        newTabSceneDataInclude,
        activeExplorerFolderPath,
        explorerExpandedFolders,
        projectExplorerEnabled,
    } = useValues(newTabSceneLogic({ tabId }))
    const {
        setSearch,
        toggleNewTabSceneDataInclude,
        refreshDataAfterToggle,
        setNewTabSearchInputRef,
        setActiveExplorerFolderPath,
        toggleExplorerFolderExpansion,
    } = useActions(newTabSceneLogic({ tabId }))
    const projectTreeLogicProps = useMemo(() => getNewTabProjectTreeLogicProps(tabId), [tabId])
    useMountedLogic(projectTreeLogic(projectTreeLogicProps))
    const { loadFolder } = useActions(projectTreeLogic(projectTreeLogicProps))
    const trimmedSearch = search.trim()

    const handleListBoxFinishedKeyDown = useCallback(
        ({ e, activeElement }: { e: ReactKeyboardEvent; activeElement: HTMLElement | null }) => {
            const isSpaceKey = e.key === ' ' || e.code === 'Space' || e.key === 'Spacebar'
            if (!isSpaceKey) {
                return
            }

            if (!projectExplorerEnabled || activeExplorerFolderPath === null || trimmedSearch !== '') {
                return
            }

            const target = activeElement
            const entryPath = target?.getAttribute('data-explorer-entry-path')
            const entryType = target?.getAttribute('data-explorer-entry-type')
            const isExpandable = target?.getAttribute('data-explorer-entry-expandable') === 'true'
            const focusKey = target?.getAttribute('data-focus-key') ?? null

            e.preventDefault()
            e.stopPropagation()

            if (entryPath && (entryType === 'folder' || isExpandable)) {
                const wasExpanded = !!explorerExpandedFolders[entryPath]
                toggleExplorerFolderExpansion(entryPath)
                if (!wasExpanded) {
                    loadFolder(entryPath)
                }
            }

            if (focusKey) {
                requestAnimationFrame(() => {
                    listboxRef.current?.focusItemByKey(focusKey)
                })
            }
        },
        [
            activeExplorerFolderPath,
            trimmedSearch,
            explorerExpandedFolders,
            toggleExplorerFolderExpansion,
            loadFolder,
            listboxRef,
            projectExplorerEnabled,
        ]
    )

    const handleAskAi = (question?: string): void => {
        const nextQuestion = (question ?? search).trim()
        router.actions.push(urls.ai(undefined, nextQuestion))
    }

    // The active commands are just the items in newTabSceneDataInclude
    const filteredActiveCommands: NEW_TAB_COMMANDS[] = projectExplorerEnabled
        ? newTabSceneDataInclude
        : newTabSceneDataInclude.filter((command) => command !== 'folders')
    const activeCommands: NEW_TAB_COMMANDS[] = filteredActiveCommands

    // Convert active commands to selected commands for the SearchInput
    // Filter out 'all' since that represents the default state (no specific filters)
    const selectedCommands: SearchInputCommand<NEW_TAB_COMMANDS>[] = activeCommands
        .filter((commandValue) => commandValue !== 'all')
        .map((commandValue) => {
            const commandInfo = NEW_TAB_COMMANDS_ITEMS.find((cmd) => cmd.value === commandValue)
            return commandInfo || { value: commandValue, displayName: commandValue }
        })

    const explorerBreadcrumbs: SearchInputBreadcrumb[] | null =
        projectExplorerEnabled && activeExplorerFolderPath !== null
            ? [
                  { label: 'Project root', path: '' },
                  ...splitPath(activeExplorerFolderPath).map((segment, index, arr) => ({
                      label: segment,
                      path: joinPath(arr.slice(0, index + 1)),
                  })),
              ]
            : null

    const searchCommands = projectExplorerEnabled
        ? NEW_TAB_COMMANDS_ITEMS
        : NEW_TAB_COMMANDS_ITEMS.filter((command) => command.value !== 'folders')

    const isExplorerActive = projectExplorerEnabled && activeExplorerFolderPath !== null
    const explorerHeaderName = !isExplorerActive
        ? null
        : activeExplorerFolderPath === ''
          ? 'Project root'
          : unescapePath(activeExplorerFolderPath)

    // Set the ref in the logic so it can be accessed from other components
    useEffect(() => {
        setNewTabSearchInputRef(commandInputRef)
    }, [setNewTabSearchInputRef])

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent): void => {
            const inputHandle = commandInputRef.current
            const inputRef = inputHandle?.getInputRef().current
            if (!inputRef) {
                return
            }

            const target = event.target as HTMLElement | null
            const isEditableTarget = target?.closest(
                'input, textarea, select, [contenteditable=""], [contenteditable="true"]'
            )
            if (isEditableTarget || document.activeElement === inputRef) {
                return
            }

            const isCharacterKey = event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey
            const isArrowKey = event.key === 'ArrowUp' || event.key === 'ArrowDown'
            const isBackspace = event.key === 'Backspace'

            if (!isCharacterKey && !isArrowKey && !isBackspace) {
                return
            }

            event.preventDefault()
            event.stopPropagation()

            inputHandle.focus()

            if (isArrowKey || isBackspace) {
                const syntheticEvent = new KeyboardEvent('keydown', {
                    key: event.key,
                    code: event.code,
                    shiftKey: event.shiftKey,
                    metaKey: event.metaKey,
                    ctrlKey: event.ctrlKey,
                    altKey: event.altKey,
                    bubbles: true,
                    cancelable: true,
                })
                inputRef.dispatchEvent(syntheticEvent)
                return
            }

            const selectionStart = inputRef.selectionStart ?? inputRef.value.length
            const selectionEnd = inputRef.selectionEnd ?? selectionStart
            if (typeof inputRef.setRangeText === 'function') {
                inputRef.setRangeText(event.key, selectionStart, selectionEnd, 'end')
            } else {
                const newValue =
                    inputRef.value.slice(0, selectionStart) + event.key + inputRef.value.slice(selectionEnd)
                inputRef.value = newValue
                inputRef.setSelectionRange(newValue.length, newValue.length)
            }
            inputRef.dispatchEvent(new Event('input', { bubbles: true }))
        }

        document.addEventListener('keydown', handleKeyDown)
        return () => {
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [])

    return (
        <>
            <ListBox
                ref={listboxRef}
                className="w-full grid grid-rows-[auto_1fr] flex-col"
                virtualFocus
                autoSelectFirst
                onFinishedKeyDown={handleListBoxFinishedKeyDown}
            >
                <div className="sr-only">
                    <p>
                        Welcome to the new tab, type / to see commands... or type a search term, you can navigate all
                        interactive elements with the keyboard
                    </p>
                </div>
                <SceneStickyBar hasSceneTitleSection={false} className="border-b">
                    <div className="px-2 @lg/main-content:px-8 pt-2 @lg/main-content:py-4 mx-auto w-full max-w-[1200px]">
                        <SearchInput
                            ref={commandInputRef}
                            commands={searchCommands}
                            value={search}
                            onChange={(value) => {
                                // Only prevent setting search if the entire value is just "/" (command mode)
                                // Allow "/" characters in other positions for normal search
                                if (value !== '/') {
                                    setSearch(value)
                                }
                            }}
                            placeholder={isExplorerActive ? 'Search in folder...' : 'Search or ask an AI question'}
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
                            explorerBreadcrumbs={explorerBreadcrumbs}
                            onExplorerBreadcrumbClick={
                                projectExplorerEnabled ? (path) => setActiveExplorerFolderPath(path) : undefined
                            }
                            onExitExplorer={isExplorerActive ? () => setActiveExplorerFolderPath(null) : undefined}
                        />
                    </div>
                    {isExplorerActive && (
                        <div className="px-4 @lg/main-content:px-8 mx-auto w-full max-w-[1200px]">
                            <SceneTitleSection
                                name={explorerHeaderName}
                                description={null}
                                resourceType={{ type: 'folder' }}
                                canEdit={false}
                                forceEdit={false}
                                noBorder
                            />
                        </div>
                    )}
                </SceneStickyBar>

                <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-4 @lg/main-content:px-8 pt-4 group/colorful-product-icons colorful-product-icons-true">
                    <div className="flex flex-col gap-2 mb-32">
                        <Results tabId={tabId || ''} listboxRef={listboxRef} handleAskAi={handleAskAi} />
                    </div>
                </div>
            </ListBox>
        </>
    )
}
