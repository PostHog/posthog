import { useSyncExternalStore } from 'react'

import type { ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

let theme: ChartTheme | null = null
let appliedMode: string | null = null
let observer: MutationObserver | null = null
const listeners = new Set<() => void>()

function current(): ChartTheme {
    if (!theme) {
        appliedMode = document.body.getAttribute('theme')
        theme = buildTheme()
    }
    return theme
}

// `useThemedHtml` writes `body[theme]` from an effect, after the render that flipped the mode, so the theme is
// rebuilt when the attribute changes rather than when the mode value does.
function reread(): void {
    const mode = document.body.getAttribute('theme')
    if (mode === appliedMode) {
        return
    }
    appliedMode = mode
    theme = buildTheme()
    listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (!observer) {
        observer = new MutationObserver(reread)
        observer.observe(document.body, { attributeFilter: ['theme'] })
        reread()
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            observer?.disconnect()
            observer = null
        }
    }
}

/**
 * The same theme as `useChartTheme`, built once per page and watched by one observer, instead of once per chart. A
 * 200-tile dashboard otherwise reads the CSS variables and adds an observer for every tile that mounts.
 */
export function useSharedChartTheme(): ChartTheme {
    return useSyncExternalStore(subscribe, current)
}
