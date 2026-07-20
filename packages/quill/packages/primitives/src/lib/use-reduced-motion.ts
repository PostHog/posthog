import * as React from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

function subscribe(onChange: () => void): () => void {
    const list = window.matchMedia(QUERY)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
}

/**
 * Whether the user asked for reduced motion.
 *
 * CSS is the right place to honour this for anything a media query can reach, so reach for this hook
 * only when it can't — SMIL (`<animate>`) is the case in quill today: it ignores CSS entirely, so the
 * only way to stop it is to not render it.
 */
function useReducedMotion(): boolean {
    return React.useSyncExternalStore(
        subscribe,
        () => window.matchMedia(QUERY).matches,
        // Server render can't know; assume motion is fine and let the client correct on hydration.
        () => false
    )
}

export { useReducedMotion }
