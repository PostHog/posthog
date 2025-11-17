import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import type { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { AppShortcutProps } from 'lib/components/AppShortcuts/AppShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isMac } from 'lib/utils'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { appShortcutLogicType } from './appShortcutLogicType'
import { openCHQueriesDebugModal } from './utils/DebugCHQueries'

export const appShortcutLogic = kea<appShortcutLogicType>([
    path(['lib', 'components', 'AppShortcuts', 'appShortcutLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeTab', 'activeTabId'], featureFlagLogic, ['featureFlags']],
        actions: [sceneLogic, ['newTab', 'removeTab']],
    })),

    actions({
        triggerNewTab: true,
        triggerCloseCurrentTab: true,
        toggleSearchBar: true,
        registerAppShortcut: (tabId: string, shortcut: AppShortcut) => ({ tabId, shortcut }),
        unregisterAppShortcut: (tabId: string, shortcutId: string) => ({ tabId, shortcutId }),
        setOptionKeyHeld: (held: boolean) => ({ held }),
        setCommandKeyHeld: (held: boolean) => ({ held }),
        setAppShortcutMenuOpen: (open: boolean) => ({ open }),
    }),

    reducers({
        appShortcuts: [
            {} as Record<string, Record<string, AppShortcut>>,
            {
                registerAppShortcut: (state, { tabId, shortcut }) => ({
                    ...state,
                    [tabId]: {
                        ...state[tabId],
                        [shortcut.id]: shortcut,
                    },
                }),
                unregisterAppShortcut: (state, { tabId, shortcutId }) => {
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
        commandKeyHeld: [
            false,
            {
                setCommandKeyHeld: (_, { held }) => held,
            },
        ],
        appShortcutMenuOpen: [
            false,
            {
                setAppShortcutMenuOpen: (_, { open }) => open,
            },
        ],
    }),

    selectors(() => ({
        shortcuts: [
            (s) => [s.appShortcutMenuOpen, s.featureFlags],
            (appShortcutMenuOpen, featureFlags): AppShortcuts => {
                // Reserved shortcuts, please don't use them
                // command+option+j = browser open dev tools
                return {
                    app: {
                        search: {
                            keys: ['command', 'k'],
                            description: 'Search',
                            onAction: () => {
                                if (removeProjectIdIfPresent(router.values.location.pathname) === urls.newTab()) {
                                    const activeTabId = sceneLogic.values.activeTabId

                                    // Try to find mounted logic instances
                                    const allMounted = newTabSceneLogic.findAllMounted()
                                    const mountedLogic = activeTabId
                                        ? newTabSceneLogic.findMounted({ tabId: activeTabId })
                                        : null
                                    if (mountedLogic) {
                                        mountedLogic.actions.focusNewTabSearchInput()
                                    } else if (allMounted.length > 0) {
                                        // Use the first available mounted logic
                                        allMounted[0].actions.focusNewTabSearchInput()
                                    }
                                    return
                                }
                                router.actions.push(urls.newTab())
                            },
                        },
                        toggleShortcutMenu: {
                            keys: ['command', 'shift', 'k'],
                            description: appShortcutMenuOpen ? 'Close shortcut menu' : 'Open shortcut menu',
                            onAction: () => {
                                if (featureFlags[FEATURE_FLAGS.APP_SHORTCUTS]) {
                                    appShortcutLogic.actions.setAppShortcutMenuOpen(!appShortcutMenuOpen)
                                }
                            },
                            order: 999,
                        },
                        newTab: {
                            keys: ['command', 'option', 't'],
                            description: 'New tab',
                            onAction: () => appShortcutLogic.actions.triggerNewTab(),
                            order: -2,
                        },
                        closeCurrentTab: {
                            keys: ['command', 'option', 'w'],
                            description: 'Close current tab',
                            onAction: () => appShortcutLogic.actions.triggerCloseCurrentTab(),
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
                    },
                }
            },
        ],

        activeAppShortcuts: [
            (s) => [s.appShortcuts, (state, props) => sceneLogic.selectors.activeTabId(state, props)],
            (appShortcuts: Record<string, Record<string, AppShortcut>>, activeTabId: string | null): AppShortcut[] => {
                if (!activeTabId || !appShortcuts[activeTabId]) {
                    return []
                }
                return Object.values(appShortcuts[activeTabId]).filter((shortcut) => shortcut.enabled)
            },
        ],

        appShortcutsByScene: [
            (s) => [s.appShortcuts, (state, props) => sceneLogic.selectors.activeTabId(state, props)],
            (appShortcuts: Record<string, Record<string, AppShortcut>>, activeTabId: string | null) =>
                (sceneKey?: string): AppShortcut[] => {
                    if (!activeTabId || !appShortcuts[activeTabId]) {
                        return []
                    }
                    const allShortcuts = Object.values(appShortcuts[activeTabId])
                    return sceneKey ? allShortcuts.filter((shortcut) => shortcut.sceneKey === sceneKey) : allShortcuts
                },
        ],

        appShortcutConflicts: [
            (s) => [s.activeAppShortcuts],
            (shortcuts: AppShortcut[]): string[] => {
                const conflicts: string[] = []
                const keyMap = new Map<string, AppShortcut[]>()

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
    })),

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
                const commandKey = isMac() ? event.metaKey : event.ctrlKey

                // Track option key state (but don't interfere with shortcuts)
                if (event.altKey && !values.optionKeyHeld) {
                    actions.setOptionKeyHeld(true)
                }

                if (commandKey) {
                    if (!values.commandKeyHeld) {
                        actions.setCommandKeyHeld(true)
                    }
                }

                // Handle shortcuts - combine app shortcuts with scene shortcuts
                const appShortcuts = Object.values(values.shortcuts.app).filter((shortcut) => shortcut.onAction)
                const activeShortcuts = [...appShortcuts, ...values.activeAppShortcuts]

                if (activeShortcuts.length === 0) {
                    return
                }

                // Build current key combination in the same order as shortcuts are defined
                const pressedKeys: string[] = []
                if (commandKey) {
                    pressedKeys.push('command')
                }
                if (event.shiftKey) {
                    pressedKeys.push('shift')
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
                    // Call action or onAction depending on shortcut type
                    if ('action' in matchingShortcut && matchingShortcut.action) {
                        matchingShortcut.action()
                    } else if ('onAction' in matchingShortcut && matchingShortcut.onAction) {
                        matchingShortcut.onAction()
                    }
                }
            }

            const onKeyUp = (event: KeyboardEvent): void => {
                const commandKey = isMac() ? event.metaKey : event.ctrlKey

                // Track option key release
                if (!event.altKey && values.optionKeyHeld) {
                    actions.setOptionKeyHeld(false)
                }

                if (!commandKey && values.commandKeyHeld) {
                    actions.setCommandKeyHeld(false)
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

type ShortcutDefinition = Omit<AppShortcutProps, 'children'>

export type AppShortcuts = {
    app: Record<string, ShortcutDefinition>
} & {
    [key in Scene]?: Record<string, ShortcutDefinition>
}
