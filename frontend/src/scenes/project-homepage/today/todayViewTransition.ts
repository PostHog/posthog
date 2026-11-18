import { router } from 'kea-router'
import type { MouseEvent } from 'react'
import { flushSync } from 'react-dom'

export function isPlainClick(event: MouseEvent): boolean {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
}

export function navigateWithCrossfade(to: string): void {
    if (
        typeof document.startViewTransition !== 'function' ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
        router.actions.push(to)
        return
    }
    document.documentElement.dataset.todayTransition = ''
    const transition = document.startViewTransition(() => flushSync(() => router.actions.push(to)))
    void transition.finished.finally(() => {
        delete document.documentElement.dataset.todayTransition
    })
}
