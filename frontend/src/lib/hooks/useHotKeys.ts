import { useEffect } from 'react'
import { Keys } from '~/types'
import { useEventListener } from './useEventListener'

export interface HotKeyInterface {
    action: () => void
    disabled?: boolean
}

export type HotKeys = Partial<Record<Keys, HotKeyInterface>>

export function useHotKeys(hotkeys: HotKeys): void {
    useEffect(() => {
        useEventListener('keydown', (event) => {
            const key = (event as KeyboardEvent).key

            // Ignore typing on inputs (default behavior); except Esc key
            if (key !== 'Escape' && (event.target as HTMLElement).tagName === 'INPUT') {
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
        })
    }, [hotkeys])
}
