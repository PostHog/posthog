import { actions, afterMount, beforeUnmount, kea, path, reducers } from 'kea'

import type { appShortcutDeuxLogicType } from './appShortcutDeuxLogicType'

export interface AppShortcutDeuxType {
    // The ref to the element to focus on
    ref: React.RefObject<HTMLElement>
    // The name of the shortcut used for reference
    name: string
    // The keybind to use for the shortcut
    keybind: string[]
    // Describe what the shortcut does
    intent: string
    // The type of interaction to trigger
    interaction: 'click' | 'focus'
    // The scope of the shortcut - 'global' or a specific scene key
    scope?: string
}

export const appShortcutDeuxLogic = kea<appShortcutDeuxLogicType>([
    path(['lib', 'components', 'AppShortcuts', 'appShortcutDeuxLogic']),
    actions({
        registerAppShortcut: (appShortcut: AppShortcutDeuxType) => ({ appShortcut }),
        unregisterAppShortcut: (name: string) => ({ name }),
    }),
    reducers({
        registeredAppShortcuts: [
            [] as AppShortcutDeuxType[],
            {
                registerAppShortcut: (state, { appShortcut }) => [...state, appShortcut],
                unregisterAppShortcut: (state, { name }) => state.filter((shortcut) => shortcut.name !== name),
            },
        ],
    }),
    afterMount(({ values, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.shiftKey && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()

                // We use & store 'command' instead of 'meta'/'ctrl' because it's more consistent with the rest of the app
                // 'ctrl' is supported as functional keybind, just not here for comparison purposes
                const keybind = [`command`, `shift`, `${event.key}`]

                const thisRegisteredAppShortcut = values.registeredAppShortcuts.find(
                    (shortcut) => shortcut.keybind.join('+') === keybind.join('+')
                )

                if (thisRegisteredAppShortcut) {
                    if (thisRegisteredAppShortcut.interaction === 'click') {
                        thisRegisteredAppShortcut.ref.current?.click()
                    } else if (thisRegisteredAppShortcut.interaction === 'focus') {
                        thisRegisteredAppShortcut.ref.current?.focus()
                    }
                }
            }
        }

        window.addEventListener('keydown', cache.onKeyDown)
        window.addEventListener('keyup', cache.onKeyUp)
        window.addEventListener('blur', cache.onBlur)
    }),
    beforeUnmount(({ cache }) => {
        // unregister app shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
        window.removeEventListener('keyup', cache.onKeyUp)
        window.removeEventListener('blur', cache.onBlur)
    }),
])
