import { useEffect, useRef, useState } from 'react'

import { CUSTOM_THEME_STYLES_ID } from 'lib/constants'

/** `theme` is what this app sets on `<body>`; `class`/`data-theme` cover the conventions the quill
 *  packages watch, so a value read here stays correct if a host switches to one of those. */
const THEME_ATTRIBUTES = ['class', 'theme', 'data-theme']

const listeners = new Set<() => void>()
let observers: MutationObserver[] | null = null

function notify(): void {
    listeners.forEach((listener) => listener())
}

/** One set of observers for the whole app rather than a pair per chart — a dashboard mounts dozens. */
function startObserving(): void {
    const attributeObserver = new MutationObserver(notify)
    attributeObserver.observe(document.documentElement, { attributeFilter: THEME_ATTRIBUTES })
    attributeObserver.observe(document.body, { attributeFilter: THEME_ATTRIBUTES })

    // A custom CSS theme redefines the same variables without touching any of those attributes.
    const customThemeObserver = new MutationObserver((records) => {
        const touchesCustomTheme = records.some((record) =>
            [...record.addedNodes, ...record.removedNodes].some(
                (node) => (node as Element).id === CUSTOM_THEME_STYLES_ID
            )
        )
        if (touchesCustomTheme) {
            notify()
        }
    })
    customThemeObserver.observe(document.head, { childList: true })

    observers = [attributeObserver, customThemeObserver]
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (!observers) {
        startObserving()
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            observers?.forEach((observer) => observer.disconnect())
            observers = null
        }
    }
}

/** Reads a design token out of computed styles, and re-reads it whenever the applied theme changes.
 *
 *  Anything canvas-rendered needs this, because it holds a copy of a color instead of resolving a CSS
 *  variable on every paint. Keying that copy on `isDarkModeOn` isn't enough: the app applies a theme
 *  by writing `document.body[theme]` from an effect in `useThemedHtml`, which runs *after* the render
 *  that flipped the value, so a render-time read returns the outgoing theme's variables and keeps
 *  them until the next reload. Watching the DOM is independent of that ordering.
 *
 *  `read` should be stable (module-level or memoized), and its result JSON-serializable — an
 *  unchanged result keeps the previous value so unrelated `class` and `<style>` churn doesn't force a
 *  redraw. */
export function useAppliedThemeValue<T>(read: () => T): T {
    const [value, setValue] = useState<T>(read)
    const readRef = useRef(read)
    readRef.current = read

    useEffect(() => {
        const sync = (): void =>
            setValue((current) => {
                const next = readRef.current()
                return JSON.stringify(current) === JSON.stringify(next) ? current : next
            })
        // The theme may already have been applied between this hook's first render and here.
        sync()
        return subscribe(sync)
    }, [])

    return value
}
