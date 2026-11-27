import { useEffect } from 'react'

import type { DashboardAction, DashboardController } from '../core/dashboardContext'

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        !!target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor')
    )
}

/** Cmd or Ctrl+Z undoes, and Shift+Z or Y redoes, unless the person is typing in a field. */
export function useUndoShortcut(
    history: DashboardController['history'] | undefined,
    can: (action: DashboardAction) => boolean
): void {
    useEffect(() => {
        if (!history || !can('undo')) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                if (can('redo')) {
                    history.onRedo()
                }
            } else {
                history.onUndo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [history, can])
}
