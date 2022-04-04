import { useEventListener } from 'lib/hooks/useEventListener'
import { DependencyList } from 'react'
import { HotKeys } from '~/types'

export interface HotkeyInterface {
    action: () => void
    disabled?: boolean
}

type HotkeysInterface = Partial<Record<HotKeys, HotkeyInterface>>
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

const exceptions = ['.hotkey-block', '.hotkey-block *']

/**
 *
 * @param hotkeys Hotkeys to listen to and actions to execute
 * @param deps List of dependencies for the hook
 */
export function useKeyboardHotkeys(hotkeys: HotkeysInterface, deps?: DependencyList): void {
    const IGNORE_INPUTS = ['input', 'textarea'] // Inputs in which hotkey events will be ignored

    useEventListener(
        'keydown',
        (event) => {
            const key = event.key

            // Ignore if the key is pressed with a meta or control key (these are general browser commands; e.g. Cmd + R)
            if (event.metaKey || event.ctrlKey || event.altKey) {
                return
            }

            // Ignore explicit hotkey exceptions
            if (exceptions.some((exception) => (event.target as Element).matches(exception))) {
                return
            }

            // Ignore typing on inputs (default behavior); except Esc key
            const isDOMInput = IGNORE_INPUTS.includes((event.target as HTMLElement).tagName.toLowerCase())
            if (key !== 'Escape' && (isDOMInput || isToolbarInput(event, IGNORE_INPUTS))) {
                return
            }

            for (const relevantKey of Object.keys(hotkeys)) {
                const hotkey = hotkeys[relevantKey as HotKeys]

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
