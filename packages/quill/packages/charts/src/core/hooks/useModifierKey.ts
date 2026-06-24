import { useEffect, useState } from 'react'

import type { ModifierKey } from '../types'

function isModifierHeld(modifier: ModifierKey, e: KeyboardEvent): boolean {
    if (modifier === 'shift') {
        return e.shiftKey
    }
    if (modifier === 'alt') {
        return e.altKey
    }
    return e.metaKey
}

/** Tracks whether a keyboard modifier (Shift/Alt/Meta) is currently held, for charts that offer a
 *  "hold to isolate" interaction. Listens on `window` so the key registers without the chart being
 *  focused, reads the live modifier flag off each key event (so chords resolve correctly), and
 *  resets on blur so a key released while another window had focus can't leave the modifier stuck.
 *  Returns `false` and attaches no listeners when `modifier` is undefined. */
export function useModifierKey(modifier: ModifierKey | undefined): boolean {
    const [active, setActive] = useState(false)
    useEffect(() => {
        if (!modifier) {
            setActive(false)
            return
        }
        const sync = (e: KeyboardEvent): void => setActive(isModifierHeld(modifier, e))
        const reset = (): void => setActive(false)
        window.addEventListener('keydown', sync)
        window.addEventListener('keyup', sync)
        window.addEventListener('blur', reset)
        return () => {
            window.removeEventListener('keydown', sync)
            window.removeEventListener('keyup', sync)
            window.removeEventListener('blur', reset)
            setActive(false)
        }
    }, [modifier])
    return active
}
