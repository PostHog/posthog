import { useValues } from 'kea'
import { RefObject, useEffect, useRef } from 'react'

import { navSwitchLogic } from './navSwitchLogic'

/**
 * A ref for the menu row that the switch hint points at. While the hint shows, the row takes focus, which is how a menu
 * marks its active row, so it reads as highlighted.
 */
export function useSwitchHintFocus<T extends HTMLElement>(): RefObject<T> {
    const { switchHintVisible } = useValues(navSwitchLogic)
    const ref = useRef<T>(null)

    useEffect(() => {
        if (!switchHintVisible) {
            return
        }
        // The menu focuses itself as it opens, so wait a frame.
        const frame = requestAnimationFrame(() => ref.current?.focus({ preventScroll: true }))
        return () => cancelAnimationFrame(frame)
    }, [switchHintVisible])

    return ref
}
