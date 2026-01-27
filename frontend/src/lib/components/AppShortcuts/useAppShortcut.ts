import { useActions } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { isMac } from 'lib/utils'

import { AppShortcutType, appShortcutLogic } from './appShortcutLogic'

const IS_MAC = isMac()

export function convertPlatformKeybind(keybind: string[]): string[] {
    return keybind.map((key) => (!IS_MAC && key === 'command' ? 'ctrl' : key))
}

export function convertPlatformKeybinds(keybinds: string[][]): string[][] {
    return keybinds.map(convertPlatformKeybind)
}

interface UseAppShortcutBase {
    /** Unique identifier for the shortcut */
    name: string
    /** Keybind(s) - use 'command' for Cmd/Ctrl. Multiple arrays = alternative keybinds */
    keybind: string[][]
    /** Description of what the shortcut does */
    intent: string
    /** Scope: 'global' or a specific Scene key */
    scope?: AppShortcutType['scope']
    /** When true, shortcut is not registered */
    disabled?: boolean
    /** Higher priority items appear first in their group. Default: 0 */
    priority?: number
}

interface UseAppShortcutWithRef extends UseAppShortcutBase {
    /** 'click' triggers element.click(), 'focus' triggers element.focus() */
    interaction: 'click' | 'focus'
    /** Optional: use your own ref instead of the one returned by the hook */
    externalRef?: React.RefObject<HTMLElement>
    callback?: never
}

interface UseAppShortcutWithCallback extends UseAppShortcutBase {
    /** 'function' calls your callback directly - no ref needed */
    interaction: 'function'
    /** The function to call when the shortcut is triggered */
    callback: () => void
    externalRef?: never
}

export type UseAppShortcutOptions = UseAppShortcutWithRef | UseAppShortcutWithCallback

export interface UseAppShortcutReturn<T extends HTMLElement> {
    /** Object ref - use this if you just need a simple ref */
    ref: React.RefObject<T>
    /** Callback ref - use this if you need to know when the element mounts (e.g., for conditional rendering) */
    callbackRef: (node: T | null) => void
}

/**
 * Hook to register a keyboard shortcut that triggers an action.
 *
 * There are two modes:
 *
 * **1. Element interaction (click/focus)** - triggers click() or focus() on an element
 * ```tsx
 * // Simple: use the returned ref
 * const { ref } = useAppShortcut({
 *     name: 'open-search',
 *     keybind: [['command', 'k']],
 *     intent: 'Open search',
 *     interaction: 'click',
 * })
 * return <button ref={ref}>Search</button>
 *
 * // Or bring your own ref
 * const myRef = useRef<HTMLButtonElement>(null)
 * useAppShortcut({
 *     name: 'open-search',
 *     keybind: [['command', 'k']],
 *     intent: 'Open search',
 *     interaction: 'click',
 *     externalRef: myRef,
 * })
 * return <button ref={myRef}>Search</button>
 * ```
 *
 * **2. Function callback** - calls a function directly, no element needed
 * ```tsx
 * useAppShortcut({
 *     name: 'toggle-theme',
 *     keybind: [['command', 'd']],
 *     intent: 'Toggle dark mode',
 *     interaction: 'function',
 *     callback: () => toggleTheme(),
 * })
 * // No ref needed - returned ref/callbackRef can be ignored
 * ```
 *
 * **When to use `ref` vs `callbackRef`:**
 * - `ref` (object ref): Use for most cases. Simple to attach.
 * - `callbackRef`: Use when the element renders conditionally or you need
 *   to know exactly when it mounts. The shortcut won't register until
 *   the element exists in the DOM.
 *
 * **Multiple keybinds:**
 * ```tsx
 * keybind: [['command', 'k'], ['command', 'shift', 'k']]  // Either triggers it
 * ```
 */
export function useAppShortcut<T extends HTMLElement = HTMLElement>(
    options: UseAppShortcutOptions
): UseAppShortcutReturn<T> {
    const { name, keybind, intent, interaction, scope = 'global', disabled = false, priority } = options

    const internalRef = useRef<T>(null)
    const [isRefReady, setIsRefReady] = useState(false)
    const { registerAppShortcut, unregisterAppShortcut } = useActions(appShortcutLogic)

    const externalRef = options.interaction !== 'function' ? options.externalRef : undefined
    const callback = options.interaction === 'function' ? options.callback : undefined

    const ref = (externalRef as React.RefObject<T>) ?? internalRef

    const callbackRef = useCallback((node: T | null) => {
        ;(internalRef as React.MutableRefObject<T | null>).current = node
        setIsRefReady(!!node)
    }, [])

    useEffect(() => {
        if (disabled) {
            return
        }

        if (interaction === 'function' && callback) {
            const platformAgnosticKeybinds = convertPlatformKeybinds(keybind)
            registerAppShortcut({
                name,
                keybind: platformAgnosticKeybinds,
                callback,
                intent,
                interaction: 'function',
                scope,
                priority,
            })
        } else if (isRefReady && ref.current && interaction !== 'function') {
            const platformAgnosticKeybinds = convertPlatformKeybinds(keybind)
            registerAppShortcut({
                name,
                keybind: platformAgnosticKeybinds,
                ref: ref as React.RefObject<HTMLElement>,
                intent,
                interaction,
                scope,
                priority,
            })
        }

        return () => {
            unregisterAppShortcut(name)
        }
    }, [isRefReady, name, intent, interaction, scope, disabled, ref, callback, priority, registerAppShortcut]) // oxlint-disable-line react-hooks/exhaustive-deps

    return { ref, callbackRef }
}
