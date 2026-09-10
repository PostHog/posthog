import { editor, IDisposable } from 'monaco-editor'

// Monaco's built-in context-menu "Paste" command runs document.execCommand('paste'), which browsers
// block, so clicking it silently does nothing. (Keyboard Cmd/Ctrl+V keeps working because in the
// browser Monaco leaves paste to the native paste event rather than to this command.) We override the
// command to read the clipboard via the async API instead. Registering under the built-in command id
// means Monaco's existing single context-menu item runs our handler — we deliberately do NOT add a
// second menu item, which would show up as a duplicate "Paste" entry.

// The command handler isn't told which editor it was triggered from, so we track the most recently
// focused / right-clicked editor and paste into that one.
let activeEditor: editor.ICodeEditor | null = null
let overrideRegistered = false

function registerClipboardPasteOverride(): void {
    if (overrideRegistered || !navigator.clipboard?.readText) {
        return
    }
    overrideRegistered = true
    editor.registerCommand('editor.action.clipboardPasteAction', (): void => {
        const targetEditor = activeEditor
        if (!targetEditor) {
            return
        }
        void navigator.clipboard.readText().then(
            (text) => {
                if (text) {
                    // Use the 'paste' handler, not 'type': 'type' runs each character through Monaco's
                    // typing interceptors (auto-closing brackets, auto-indent), which corrupts pasted
                    // code. 'paste' inserts the text verbatim like a native paste.
                    targetEditor.trigger('keyboard', 'paste', { text })
                }
            },
            (error) => {
                // A denied/unavailable clipboard-read permission is expected — the user can still use
                // Cmd/Ctrl+V. Surface anything else so it stays visible in dev.
                if (!(error instanceof DOMException)) {
                    console.warn('Failed to paste from clipboard', error)
                }
            }
        )
    })
}

/**
 * Make Monaco's right-click "Paste" actually work for this editor (see comment above for why the
 * built-in is broken in the browser). Returns a disposable that detaches the editor tracking.
 */
export function enableClipboardPaste(editorInstance: editor.ICodeEditor): IDisposable {
    registerClipboardPasteOverride()
    const disposables = [
        editorInstance.onDidFocusEditorText(() => {
            activeEditor = editorInstance
        }),
        editorInstance.onContextMenu(() => {
            activeEditor = editorInstance
        }),
        editorInstance.onDidDispose(() => {
            if (activeEditor === editorInstance) {
                activeEditor = null
            }
        }),
    ]
    return {
        dispose: () => disposables.forEach((d) => d.dispose()),
    }
}
