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

function isSequenceKeybind(keybind: string[]): boolean {
    return keybind.includes('then')
}

function isSingleKeyKeybind(keybind: string[]): boolean {
    return keybind.length === 1 && !['command', 'option', 'shift', 'ctrl'].includes(keybind[0])
}

function getSequenceKeys(keybind: string[]): string[] {
    return keybind.filter((key) => key !== 'then')
}

function triggerShortcut(shortcut: AppShortcutType): void {
    if (shortcut.interaction === 'click') {
        shortcut.ref.current?.click()
    } else if (shortcut.interaction === 'focus') {
        shortcut.ref.current?.focus()
    } else if (shortcut.interaction === 'function') {
        shortcut.callback()
    }
}

function isEditableElement(target: EventTarget | null): boolean {
    if (!target || !(target instanceof HTMLElement)) {
        return false
    }
    const tagName = target.tagName.toLowerCase()
    return (
        tagName === 'input' ||
        tagName === 'textarea' ||
        tagName === 'select' ||
        target.isContentEditable ||
        target.closest('.monaco-editor') !== null
    )
}

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
        // Sequence shortcut state
        cache.sequenceKeys = [] as string[]
        cache.sequenceShortcut = null as AppShortcutType | null
        cache.sequenceLastKeyTime = 0

        cache.onKeyDown = (event: KeyboardEvent) => {
            const commandKey = event.metaKey || event.ctrlKey

            // Handle modifier-based shortcuts (Cmd+K, etc.)
            if (commandKey) {
                // Reset any in-progress sequence
                cache.sequenceKeys = []
                cache.sequenceShortcut = null

                const pressedKeys: string[] = ['command']
                if (event.shiftKey) {
                    pressedKeys.push('shift')
                }
                if (event.altKey) {
                    pressedKeys.push('option')
                }

                // Handle Alt key combinations - event.key can change with Alt held
                let keyToAdd = event.key.toLowerCase()
                if (event.altKey) {
                    const codeMatch = event.code.match(/^Key([A-Z])$/)
                    if (codeMatch) {
                        keyToAdd = codeMatch[1].toLowerCase()
                    } else if (event.code === 'Tab') {
                        keyToAdd = 'tab'
                    }
                }

                pressedKeys.push(keyToAdd)
                const pressedKeyString = pressedKeys.join('+')

                const matchingShortcut = values.registeredAppShortcuts.find((shortcut) =>
                    shortcut.keybind.some(
                        (keybind) =>
                            !isSequenceKeybind(keybind) &&
                            keybind.map((k) => k.toLowerCase()).join('+') === pressedKeyString
                    )
                )

                if (matchingShortcut) {
                    event.preventDefault()
                    event.stopPropagation()
                    triggerShortcut(matchingShortcut)
                }
                return
            }

            // Handle sequence shortcuts (no modifier keys, not in editable elements)
            if (isEditableElement(event.target) || event.altKey) {
                return
            }

            const now = Date.now()
            const key = event.key.toLowerCase()

            // Check for single-key shortcuts first (immediate trigger, no sequence)
            // Since single key shortcuts trigger eagerly, sequence shortcuts need to
            // check for collisions before being implemented. We could also make this
            // "lazy" but that would result in a noticeable lag in app for single key
            // shortcuts. My preference is the eager way
            const singleKeyMatch = values.registeredAppShortcuts.find((shortcut) =>
                shortcut.keybind.some((keybind) => isSingleKeyKeybind(keybind) && keybind[0] === key)
            )

            if (singleKeyMatch) {
                event.preventDefault()
                event.stopPropagation()
                cache.sequenceKeys = []
                cache.sequenceShortcut = null
                triggerShortcut(singleKeyMatch)
                return
            }

            // Reset if too much time has passed (1.5s)
            if (now - cache.sequenceLastKeyTime > 1500) {
                cache.sequenceKeys = []
                cache.sequenceShortcut = null
            }
            cache.sequenceLastKeyTime = now

            // Build up the sequence
            cache.sequenceKeys.push(key)

            // Look for a matching sequence shortcut
            const matchingShortcut = values.registeredAppShortcuts.find((shortcut) =>
                shortcut.keybind.some((keybind) => {
                    if (!isSequenceKeybind(keybind)) {
                        return false
                    }
                    const sequenceKeys = getSequenceKeys(keybind)
                    // Check if our current keys match the end of a sequence
                    if (cache.sequenceKeys.length > sequenceKeys.length) {
                        return false
                    }
                    return sequenceKeys
                        .slice(0, cache.sequenceKeys.length)
                        .every((k: string, i: number) => k === cache.sequenceKeys[i])
                })
            )

            if (matchingShortcut) {
                const keybind = matchingShortcut.keybind.find((kb) => isSequenceKeybind(kb))!
                const sequenceKeys = getSequenceKeys(keybind)

                if (cache.sequenceKeys.length === sequenceKeys.length) {
                    // Sequence complete
                    event.preventDefault()
                    cache.sequenceKeys = []
                    cache.sequenceShortcut = null
                    triggerShortcut(matchingShortcut)
                } else {
                    // Partial match - keep tracking
                    cache.sequenceShortcut = matchingShortcut
                }
            } else {
                // No match - reset
                cache.sequenceKeys = []
                cache.sequenceShortcut = null
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
