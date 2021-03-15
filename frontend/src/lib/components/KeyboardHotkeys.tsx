import { useEventListener } from 'lib/hooks/useEventListener'
import React from 'react'
import { Keys } from '~/types'

export interface HotKeyInterface {
    action: () => void
    disabled?: boolean
}

export type HotKeys = Partial<Record<Keys, HotKeyInterface>>

export function KeyboardHotkeys({ hotkeys }: { hotkeys: HotKeys }): JSX.Element {
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
    return <></>
}
