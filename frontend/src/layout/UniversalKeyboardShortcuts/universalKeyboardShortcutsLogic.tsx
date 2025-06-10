import { actions, afterMount, beforeUnmount, connect, kea, path, reducers } from 'kea'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import type { universalKeyboardShortcutsLogicType } from './universalKeyboardShortcutsLogicType'

export type UniversalKeyboardShortcutCategory = 'nav' | 'product'
export interface UniversalKeyboardShortcutItem {
    // The ref to the element to focus on
    ref: React.RefObject<HTMLElement>
    // The name of the shortcut used for reference
    name: string
    // The category of the shortcut, used to group shortcuts in the UI
    category: UniversalKeyboardShortcutCategory
    // The keybind to use for the shortcut
    keybind: string
    // Describe what the shortcut does
    intent: string
    // The type of interaction to trigger
    interaction: 'click' | 'focus'
}

export const universalKeyboardShortcutsLogic = kea<universalKeyboardShortcutsLogicType>([
    path(['layout', 'universalKeyboardShortcuts', 'universalKeyboardShortcutsLogic']),
    connect({
        values: [panelLayoutLogic, ['panelTreeRef']],
    }),
    actions({
        registerKeyboardShortcut: (keyboardShortcut: UniversalKeyboardShortcutItem) => ({ keyboardShortcut }),
        unregisterKeyboardShortcut: (name: string) => ({ name }),
        showKeyboardShortcuts: (show: boolean) => ({ show }),
        handleKeyboardShortcut: (keybind: string) => ({ keybind }),
    }),
    reducers({
        isKeyboardShortcutsVisible: [
            false,
            {
                showKeyboardShortcuts: (_, { show }) => show,
            },
        ],
        registeredKeyboardShortcuts: [
            [] as UniversalKeyboardShortcutItem[],
            {
                registerKeyboardShortcut: (state, { keyboardShortcut }) => [...state, keyboardShortcut],
                unregisterKeyboardShortcut: (state, { name }) => state.filter((shortcut) => shortcut.name !== name),
            },
        ],
    }),
    afterMount(({ actions, values, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.shiftKey && event.metaKey) {
                event.preventDefault()
                actions.showKeyboardShortcuts(true)
                const keybind = `command shift ${event.key}`
                const thisRegisteredKeyboardShortcut = values.registeredKeyboardShortcuts.find(
                    (shortcut) => shortcut.keybind === keybind
                )

                if (thisRegisteredKeyboardShortcut) {
                    if (thisRegisteredKeyboardShortcut.interaction === 'click') {
                        thisRegisteredKeyboardShortcut.ref.current?.click()
                    } else if (thisRegisteredKeyboardShortcut.interaction === 'focus') {
                        thisRegisteredKeyboardShortcut.ref.current?.focus()
                    }
                }
            }
        }
        cache.onKeyUp = (event: KeyboardEvent) => {
            if (!event.shiftKey && !event.metaKey) {
                actions.showKeyboardShortcuts(false)
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
        window.addEventListener('keyup', cache.onKeyUp)
    }),
    beforeUnmount(({ cache }) => {
        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
        window.removeEventListener('keyup', cache.onKeyUp)
    }),
])
