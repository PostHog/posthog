import { actions, afterMount, beforeUnmount, connect, kea, path, reducers } from 'kea'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import type { universalKeyboardShortcutsLogicType } from './universalKeyboardShortcutsLogicType'

// export const PanelLayoutNavItemShortcuts: Record<string, string> = {

type keyboardShortcutItem = {
    name: string
    category: 'nav' | 'product'
    keybind: string
    ref: React.RefObject<HTMLElement>
}

export const universalKeyboardShortcutsLogic = kea<universalKeyboardShortcutsLogicType>([
    path(['layout', 'universalKeyboardShortcuts', 'universalKeyboardShortcutsLogic']),
    connect({
        values: [panelLayoutLogic, ['panelTreeRef']],
    }),
    actions({
        registerKeyboardShortcut: (keyboardShortcut: keyboardShortcutItem) => ({ keyboardShortcut }),
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
            [] as keyboardShortcutItem[],
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
                const thisRegisteredKeyboardShortcut = values.registeredKeyboardShortcuts.find((shortcut) => shortcut.keybind === keybind)

                if (thisRegisteredKeyboardShortcut) {
                    thisRegisteredKeyboardShortcut.ref.current?.click()
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
