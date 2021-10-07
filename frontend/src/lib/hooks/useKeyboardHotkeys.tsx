import { useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'
import { DependencyList } from 'react'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { GlobalHotKeys, HotKeys } from '~/types'

export interface HotkeyInterface {
    action: () => void
    disabled?: boolean
}

type LocalHotkeysInterface = Partial<Record<HotKeys, HotkeyInterface>>
export const useKeyboardHotkeys = (
    hotkeys: LocalHotkeysInterface,
    deps?: DependencyList,
    enableOnGlobal?: boolean
): void => _useKeyboardHotkeys(hotkeys, deps, enableOnGlobal)

/*
 Global keyboard hotkeys reserve special keys for shortcuts that are available everywhere 
 in the app, we separate them to avoid mixup with local commands
 */
type GlobalHotkeysInterface = Partial<Record<GlobalHotKeys, HotkeyInterface>>
export const useGlobalKeyboardHotkeys = (hotkeys: GlobalHotkeysInterface, deps?: DependencyList): void =>
    _useKeyboardHotkeys(hotkeys, deps, true)

type AllHotKeys = GlobalHotKeys | HotKeys
type AllHotkeysInterface = Partial<Record<AllHotKeys, HotkeyInterface>>

/**
 * input boxes in the hovering toolbar do not have event target of input.
 * they are detected as for e.g.div#__POSTHOG_TOOLBAR__.ph-no-capture
 * see https://developer.mozilla.org/en-US/docs/Web/API/Event/composedPath
 * @param event
 * @param ignorableElements
 */
const isToolbarInput = (event: Event, ignorableElements: string[]): boolean => {
    const path = event.composedPath() || (event as any).path
    if (!path) {
        return false
    }

    const sourceElement = path[0] as HTMLElement
    const tagName = sourceElement.tagName || 'not an html element'
    return ignorableElements.includes(tagName.toLowerCase())
}

/**
 *
 * @param hotkeys Hotkeys to listen to and actions to execute
 * @param deps List of dependencies for the hook
 * @param enableOnGlobal Whether these hotkeys should run when a globally-scoped hotkey is enabled
 */
function _useKeyboardHotkeys(hotkeys: AllHotkeysInterface, deps?: DependencyList, enableOnGlobal?: boolean): void {
    const IGNORE_INPUTS = ['input', 'textarea'] // Inputs in which hotkey events will be ignored
    const { hotkeyNavigationEngaged } = useValues(navigationLogic)

    useEventListener(
        'keydown',
        (event) => {
            const key = (event as KeyboardEvent).key

            // Ignore if the key is pressed with a meta or control key (these are general browser commands; e.g. Cmd + R)
            if (
                (event as KeyboardEvent).metaKey ||
                (event as KeyboardEvent).ctrlKey ||
                (event as KeyboardEvent).altKey
            ) {
                return
            }

            // Ignore typing on inputs (default behavior); except Esc key
            const isDOMInput = IGNORE_INPUTS.includes((event.target as HTMLElement).tagName.toLowerCase())
            if (key !== 'Escape' && (isDOMInput || isToolbarInput(event, IGNORE_INPUTS))) {
                return
            }

            // Ignore if global hotkeys are engaged and this is not intended as a global action,
            // currently this only encompasses global navigation keys
            if (!enableOnGlobal && hotkeyNavigationEngaged) {
                return
            }

            for (const relevantKey of Object.keys(hotkeys)) {
                const hotkey = hotkeys[relevantKey as AllHotKeys]

                if (!hotkey || hotkey.disabled) {
                    continue
                }

                if (key.toLowerCase() === relevantKey) {
                    event.preventDefault()
                    hotkey.action()
                    break
                }
            }
        },
        undefined,
        [hotkeys, ...(deps || [])]
    )
}
