import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import type { SceneShortcut } from 'lib/components/SceneShortcuts/SceneShortcut'
import { SceneShortcutProps } from 'lib/components/SceneShortcuts/SceneShortcut'
import { openCHQueriesDebugModal } from 'lib/components/SceneShortcuts/utils/DebugCHQueries'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import type { sceneShortcutLogicType } from './sceneShortcutLogicType'

export const sceneShortcutLogic = kea<sceneShortcutLogicType>([
    path(['lib', 'components', 'SceneShortcuts', 'sceneShortcutLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeTab', 'activeTabId']],
        actions: [sceneLogic, ['newTab', 'removeTab']],
    })),

    actions({
        triggerNewTab: true,
        triggerCloseCurrentTab: true,
        toggleSearchBar: true,
        registerSceneShortcut: (tabId: string, shortcut: SceneShortcut) => ({ tabId, shortcut }),
        unregisterSceneShortcut: (tabId: string, shortcutId: string) => ({ tabId, shortcutId }),
        setOptionKeyHeld: (held: boolean) => ({ held }),
        setActionPaletteOpen: (open: boolean) => ({ open }),
    }),

    reducers({
        sceneShortcuts: [
            {} as Record<string, Record<string, SceneShortcut>>,
            {
                registerSceneShortcut: (state, { tabId, shortcut }) => ({
                    ...state,
                    [tabId]: {
                        ...state[tabId],
                        [shortcut.id]: shortcut,
                    },
                }),
                unregisterSceneShortcut: (state, { tabId, shortcutId }) => {
                    const tabShortcuts = { ...state[tabId] }
                    delete tabShortcuts[shortcutId]
                    return {
                        ...state,
                        [tabId]: tabShortcuts,
                    }
                },
            },
        ],
        optionKeyHeld: [
            false,
            {
                setOptionKeyHeld: (_, { held }) => held,
            },
        ],
        actionPaletteOpen: [
            false,
            {
                setActionPaletteOpen: (_, { open }) => open,
            },
        ],
    }),

    selectors({
        shortcuts: [
            (s) => [s.actionPaletteOpen],
            (actionPaletteOpen: boolean): SceneShortcuts => {
                // Reserved shortcuts, please don't use them
                // command+option+j = browser open dev tools

                return {
                    app: {
                        toggleShortcutMenu: {
                            keys: ['command', 'k'],
                            description: actionPaletteOpen ? 'Close shortcut menu' : 'Open shortcut menu',
                            onAction: () => {
                                sceneShortcutLogic.actions.setActionPaletteOpen(!actionPaletteOpen)
                            },
                        },
                        newTab: {
                            keys: ['command', 'option', 't'],
                            description: 'New tab',
                            onAction: () => sceneShortcutLogic.actions.triggerNewTab(),
                            order: -2,
                        },
                        closeCurrentTab: {
                            keys: ['command', 'option', 'w'],
                            description: 'Close current tab',
                            onAction: () => sceneShortcutLogic.actions.triggerCloseCurrentTab(),
                            order: -1,
                        },
                        debugClickhouseQueries: {
                            keys: ['command', 'option', 'tab'],
                            description: 'Debug ClickHouse queries',
                            onAction: () => {
                                openCHQueriesDebugModal()
                            },
                            type: 'action',
                        },
                        toggleInfoActionsPanel: {
                            keys: ['command', 'option', 'i'],
                            description: 'Toggle Info & actions panel',
                            type: 'toggle',
                        },
                    },
                    [Scene.Dashboards]: {
                        newDashboard: {
                            keys: ['command', 'option', 'n'],
                            description: 'New dashboard',
                            sceneKey: Scene.Dashboards,
                        },
                    },
                    [Scene.Dashboard]: {
                        addTextTile: {
                            keys: ['command', 'option', 'a'],
                            description: 'Add text tile to dashboard',
                            sceneKey: Scene.Dashboard,
                        },
                        addInsightToDashboard: {
                            keys: ['command', 'option', 'n'],
                            description: 'Add insight to dashboard',
                            sceneKey: Scene.Dashboard,
                        },
                        toggleEditMode: {
                            keys: ['command', 'option', 'e'],
                            description: 'Toggle dashboard edit mode',
                            sceneKey: Scene.Dashboard,
                        },
                    },
                }
            },
        ],

        activeSceneShortcuts: [
            (s) => [s.sceneShortcuts, (state, props) => sceneLogic.selectors.activeTabId(state, props)],
            (
                sceneShortcuts: Record<string, Record<string, SceneShortcut>>,
                activeTabId: string | null
            ): SceneShortcut[] => {
                if (!activeTabId || !sceneShortcuts[activeTabId]) {
                    return []
                }
                return Object.values(sceneShortcuts[activeTabId]).filter((shortcut) => shortcut.enabled)
            },
        ],

        sceneShortcutsByScene: [
            (s) => [s.sceneShortcuts, (state, props) => sceneLogic.selectors.activeTabId(state, props)],
            (sceneShortcuts: Record<string, Record<string, SceneShortcut>>, activeTabId: string | null) =>
                (sceneKey?: string): SceneShortcut[] => {
                    if (!activeTabId || !sceneShortcuts[activeTabId]) {
                        return []
                    }
                    const allShortcuts = Object.values(sceneShortcuts[activeTabId])
                    return sceneKey ? allShortcuts.filter((shortcut) => shortcut.sceneKey === sceneKey) : allShortcuts
                },
        ],

        sceneShortcutConflicts: [
            (s) => [s.activeSceneShortcuts],
            (shortcuts: SceneShortcut[]): string[] => {
                const conflicts: string[] = []
                const keyMap = new Map<string, SceneShortcut[]>()

                shortcuts.forEach((shortcut) => {
                    const keyString = shortcut.keys.join('+')
                    if (!keyMap.has(keyString)) {
                        keyMap.set(keyString, [])
                    }
                    keyMap.get(keyString)!.push(shortcut)
                })

                keyMap.forEach((shortcutsForKey, keyString) => {
                    if (shortcutsForKey.length > 1) {
                        conflicts.push(
                            `Shortcut conflict: ${keyString} is used by ${shortcutsForKey.map((s) => s.description).join(', ')}`
                        )
                    }
                })

                return conflicts
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        triggerNewTab: () => {
            actions.newTab()
        },
        triggerCloseCurrentTab: () => {
            if (values.activeTab) {
                actions.removeTab(values.activeTab)
            }
        },
    })),

    afterMount(({ actions, cache, values }) => {
        cache.disposables.add(() => {
            const onKeyDown = (event: KeyboardEvent): void => {
                // Track option key state (but don't interfere with shortcuts)
                if (event.altKey && !values.optionKeyHeld) {
                    actions.setOptionKeyHeld(true)
                }

                // Handle scene shortcuts
                const activeShortcuts = values.activeSceneShortcuts
                if (activeShortcuts.length === 0) {
                    return
                }

                // Build current key combination
                const pressedKeys: string[] = []
                if (event.shiftKey) {
                    pressedKeys.push('shift')
                }
                if (event.ctrlKey || event.metaKey) {
                    pressedKeys.push('command')
                }
                if (event.altKey) {
                    pressedKeys.push('option')
                }

                // Handle special key mappings
                let keyToAdd = event.key.toLowerCase()

                // Handle Alt key combinations - sometimes event.key changes with Alt
                if (event.altKey) {
                    // For Alt+letter combinations, the event.key might be different
                    // Use event.code instead for more reliable detection
                    const codeMatch = event.code.match(/^Key([A-Z])$/)
                    if (codeMatch) {
                        keyToAdd = codeMatch[1].toLowerCase()
                    } else if (event.code === 'Escape') {
                        keyToAdd = 'escape'
                    }
                    // For other keys, keep using event.key.toLowerCase()
                }

                pressedKeys.push(keyToAdd)

                const pressedKeyString = pressedKeys.join('+')

                // Find matching shortcut
                const matchingShortcut = activeShortcuts.find((shortcut) => {
                    const shortcutKeyString = shortcut.keys.map((k) => k.toLowerCase()).join('+')
                    return shortcutKeyString === pressedKeyString
                })

                if (matchingShortcut) {
                    event.preventDefault()
                    event.stopPropagation()
                    matchingShortcut.action()
                    // close action palette
                    actions.setActionPaletteOpen(false)
                }
            }

            const onKeyUp = (event: KeyboardEvent): void => {
                // Track option key release
                if (!event.altKey && values.optionKeyHeld) {
                    actions.setOptionKeyHeld(false)
                }
            }

            window.addEventListener('keydown', onKeyDown)
            window.addEventListener('keyup', onKeyUp)
            return () => {
                window.removeEventListener('keydown', onKeyDown)
                window.removeEventListener('keyup', onKeyUp)
            }
        }, 'keydownListener')
    }),
])

type ShortcutDefinition = Omit<SceneShortcutProps, 'children'>

export type SceneShortcuts = {
    app: Record<string, ShortcutDefinition>
} & {
    [key in Scene]?: Record<string, ShortcutDefinition>
}
