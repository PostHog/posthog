import { useEventListener } from 'lib/hooks/useEventListener'
import { isMac } from 'lib/utils/dom'

export type TodayArchiveShortcutEvent = Pick<
    KeyboardEvent,
    'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey' | 'repeat' | 'target'
>

export function todayArchiveShortcutLabel(mac: boolean): string {
    return mac ? '⌘⇧A' : 'Ctrl+Shift+A'
}

function isTextEntry(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && (target.isContentEditable || target.matches('input, textarea, select'))
}

export function isTodayArchiveShortcut(event: TodayArchiveShortcutEvent, mac: boolean): boolean {
    const modifier = mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey
    return (
        modifier &&
        event.shiftKey &&
        !event.altKey &&
        !event.repeat &&
        event.key.toLowerCase() === 'a' &&
        !isTextEntry(event.target)
    )
}

export function useTodayArchiveShortcut(enabled: boolean, onArchive: () => void): void {
    useEventListener('keydown', (event) => {
        if (enabled && isTodayArchiveShortcut(event, isMac())) {
            event.preventDefault()
            onArchive()
        }
    })
}
