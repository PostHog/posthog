import type { Editor, JSONContent } from '@tiptap/core'
import { useEffect, type MutableRefObject } from 'react'

import { getTiptapEditorDom } from './tiptapEditorDom'

type UseMarkdownEditorControlledAndFormEffectsParams = {
    editor: Editor | null
    value: string | undefined
    markdownToDoc: (markdown: string | null | undefined) => JSONContent
    docToMarkdown: (doc: JSONContent) => string
    lastSyncedMarkdownRef: MutableRefObject<string>
    syncMarkdownFromEditor: (nextMarkdown: string, options?: { force?: boolean }) => void
}

/**
 * Controlled `value` ↔ editor sync and capture-phase form submit flush shared by rich and inline markdown editors.
 */
export function useMarkdownEditorControlledAndFormEffects({
    editor,
    value,
    markdownToDoc,
    docToMarkdown,
    lastSyncedMarkdownRef,
    syncMarkdownFromEditor,
}: UseMarkdownEditorControlledAndFormEffectsParams): void {
    useEffect(() => {
        lastSyncedMarkdownRef.current = value || ''
    }, [value, lastSyncedMarkdownRef])

    useEffect(() => {
        if (!editor) {
            return
        }

        const currentEditorMarkdown = docToMarkdown(editor.getJSON())
        const incomingMarkdown = value || ''
        if (currentEditorMarkdown !== incomingMarkdown) {
            editor.commands.setContent(markdownToDoc(incomingMarkdown), { emitUpdate: false })
        }
    }, [editor, value, docToMarkdown, markdownToDoc])

    useEffect(() => {
        if (!editor) {
            return
        }

        const editorElement = getTiptapEditorDom(editor)
        const formElement = editorElement?.closest('form')
        if (!formElement) {
            return
        }

        const handleFormSubmitCapture = (): void => {
            syncMarkdownFromEditor(docToMarkdown(editor.getJSON()), { force: true })
        }

        formElement.addEventListener('submit', handleFormSubmitCapture, true)
        return () => {
            formElement.removeEventListener('submit', handleFormSubmitCapture, true)
        }
    }, [editor, docToMarkdown, editor?.isInitialized, syncMarkdownFromEditor])
}
