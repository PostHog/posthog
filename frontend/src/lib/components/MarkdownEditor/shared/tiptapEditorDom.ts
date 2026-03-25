import type { Editor } from '@tiptap/core'

/**
 * Prefer this over `editor.view.dom`: when the ProseMirror view is not mounted yet, Tiptap's
 * `editor.view` getter returns a Proxy and property reads like `.dom` throw.
 *
 * Uses Tiptap's internal `editorView` because there is no public DOM accessor before the view exists.
 */
export function getTiptapEditorDom(editor: Editor): HTMLElement | null {
    if (editor.isDestroyed) {
        return null
    }
    try {
        const editorView = (editor as unknown as { editorView: { dom: HTMLElement } | null }).editorView
        return editorView?.dom ?? null
    } catch {
        return null
    }
}
