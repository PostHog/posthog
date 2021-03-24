import { useEventListener } from 'lib/hooks/useEventListener'
import { DependencyList } from 'react'
import { Keys } from '~/types'

export interface HotkeyInterface {
    action: () => void
    disabled?: boolean
}

export type Hotkeys = Partial<Record<Keys, HotkeyInterface>>

const IGNORE_INPUTS = ['input', 'textarea'] // Inputs in which hotkey events will be ignored

export function useKeyboardHotkeys(hotkeys: Hotkeys, deps?: DependencyList): void {
    useEventListener(
        'keydown',
        (event) => {
            const key = (event as KeyboardEvent).key

            // Ignore typing on inputs (default behavior); except Esc key
            if (key !== 'Escape' && IGNORE_INPUTS.includes((event.target as HTMLElement).tagName.toLowerCase())) {
                return
            }

            for (const relevantKey of Object.keys(hotkeys)) {
                const hotkey = hotkeys[relevantKey as Keys]

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
