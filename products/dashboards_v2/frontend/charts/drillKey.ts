import { useSyncExternalStore } from 'react'

export const DRILL_KEY = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

let held = false
const listeners = new Set<() => void>()

function setHeld(next: boolean): void {
    if (next !== held) {
        held = next
        listeners.forEach((listener) => listener())
    }
}

const onKey = (event: KeyboardEvent): void => setHeld(event.metaKey || event.ctrlKey)
const onBlur = (): void => setHeld(false)

function subscribe(listener: () => void): () => void {
    if (!listeners.size) {
        window.addEventListener('keydown', onKey)
        window.addEventListener('keyup', onKey)
        window.addEventListener('blur', onBlur)
    }
    listeners.add(listener)
    return () => {
        listeners.delete(listener)
        if (!listeners.size) {
            window.removeEventListener('keydown', onKey)
            window.removeEventListener('keyup', onKey)
            window.removeEventListener('blur', onBlur)
        }
    }
}

const unsubscribed = (): (() => void) => () => {}

export function useDrillKey(enabled: boolean): boolean {
    return useSyncExternalStore(
        enabled ? subscribe : unsubscribed,
        () => enabled && held,
        () => false
    )
}
