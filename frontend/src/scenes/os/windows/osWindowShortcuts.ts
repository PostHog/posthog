export type OsWindowCommand = 'snap-left' | 'snap-right' | 'toggle-maximize' | 'minimize' | 'close' | 'tidy-up'

export type OsWindowShortcutEvent = Pick<
    KeyboardEvent,
    'code' | 'altKey' | 'shiftKey' | 'ctrlKey' | 'metaKey' | 'repeat' | 'isComposing' | 'target'
> & { composedPath?: () => EventTarget[] }

// Keys are matched by `code` because Option+Shift on macOS turns `key` into a symbol.
const COMMANDS: Record<string, OsWindowCommand> = {
    ArrowLeft: 'snap-left',
    ArrowRight: 'snap-right',
    ArrowUp: 'toggle-maximize',
    ArrowDown: 'minimize',
    KeyW: 'close',
    KeyG: 'tidy-up',
}

export const OS_WINDOW_SHORTCUT_KEYS: Record<OsWindowCommand, string[]> = {
    'snap-left': ['option', 'shift', 'arrowleft'],
    'snap-right': ['option', 'shift', 'arrowright'],
    'toggle-maximize': ['option', 'shift', 'arrowup'],
    minimize: ['option', 'shift', 'arrowdown'],
    close: ['option', 'shift', 'w'],
    'tidy-up': ['option', 'shift', 'g'],
}

function isEditable(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/**
 * Window shortcuts need Alt+Shift (Option+Shift on macOS) and nothing else, so they never take a bare
 * key, text selection (Shift+arrow), browser back (Alt+arrow) or the app's own Cmd+Option shortcuts.
 * They only reach this page while the desktop has focus: key presses inside a window stay in its frame.
 */
export function osWindowCommandFor(event: OsWindowShortcutEvent): OsWindowCommand | null {
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey || event.repeat || event.isComposing) {
        return null
    }
    // An editor inside a shadow root reports its host as the target, so the innermost element is checked.
    if (isEditable(event.composedPath?.()[0] ?? event.target)) {
        return null
    }
    return COMMANDS[event.code] ?? null
}
