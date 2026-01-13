import { actions, afterMount, beforeUnmount, kea, path, reducers } from 'kea'

import { Scene } from 'scenes/sceneTypes'

import type { appShortcutLogicType } from './appShortcutLogicType'

interface AppShortcutBase {
    name: string
    keybind: string[][]
    intent: string
    scope?: 'global' | keyof typeof Scene
    /** Higher priority items appear first in their group. Default: 0 */
    priority?: number
}

interface AppShortcutWithRef extends AppShortcutBase {
    ref: React.RefObject<HTMLElement>
    interaction: 'click' | 'focus'
    callback?: never
}

interface AppShortcutWithCallback extends AppShortcutBase {
    callback: () => void
    interaction: 'function'
    ref?: never
}

export type AppShortcutType = AppShortcutWithRef | AppShortcutWithCallback

export const appShortcutLogic = kea<appShortcutLogicType>([
    path(['lib', 'components', 'AppShortcuts', 'appShortcutLogic']),
    actions({
        registerAppShortcut: (appShortcut: AppShortcutType) => ({ appShortcut }),
        unregisterAppShortcut: (name: string) => ({ name }),
        setAppShortcutMenuOpen: (open: boolean) => ({ open }),
    }),
    reducers({
        registeredAppShortcuts: [
            [] as AppShortcutType[],
            {
                registerAppShortcut: (state, { appShortcut }) => {
                    // Remove any existing shortcut with the same name, then add the new one
                    const filtered = state.filter((shortcut) => shortcut.name !== appShortcut.name)
                    return [...filtered, appShortcut]
                },
                unregisterAppShortcut: (state, { name }) => state.filter((shortcut) => shortcut.name !== name),
            },
        ],
        appShortcutMenuOpen: [
            false,
            {
                setAppShortcutMenuOpen: (_, { open }) => open,
            },
        ],
    }),
    afterMount(({ values, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            const commandKey = event.metaKey || event.ctrlKey

            if (commandKey) {
                // Build current key combination in the same order as shortcuts are defined
                const pressedKeys: string[] = []

                pressedKeys.push('command')

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
                    } else if (event.code === 'Tab') {
                        keyToAdd = 'tab'
                    }
                    // For other keys, keep using event.key.toLowerCase()
                }

                pressedKeys.push(keyToAdd)
                const pressedKeyString = pressedKeys.join('+')

                // Find matching shortcut
                const matchingShortcut = values.registeredAppShortcuts.find((shortcut) => {
                    return shortcut.keybind.some((keybind) => {
                        const shortcutKeyString = keybind.map((k: string) => k.toLowerCase()).join('+')
                        return shortcutKeyString === pressedKeyString
                    })
                })

                if (matchingShortcut) {
                    event.preventDefault()
                    event.stopPropagation()

                    if (matchingShortcut.interaction === 'click') {
                        matchingShortcut.ref.current?.click()
                    } else if (matchingShortcut.interaction === 'focus') {
                        matchingShortcut.ref.current?.focus()
                    } else if (matchingShortcut.interaction === 'function') {
                        matchingShortcut.callback()
                    }
                }
            }
        }

        window.addEventListener('keydown', cache.onKeyDown, { capture: true })
        window.addEventListener('keyup', cache.onKeyUp)
        window.addEventListener('blur', cache.onBlur)
    }),
    beforeUnmount(({ cache }) => {
        // unregister app shortcuts
        window.removeEventListener('keydown', cache.onKeyDown, { capture: true })
        window.removeEventListener('keyup', cache.onKeyUp)
        window.removeEventListener('blur', cache.onBlur)
    }),
])
