import type { CodeEditorProps } from 'lib/monaco/CodeEditor'
import { escapePropertyAsHogQLIdentifier } from 'lib/utils/hogql'

export type CodeEditorInstance = Parameters<NonNullable<CodeEditorProps['onMount']>>[0]

export function insertOutputColumn(editor: CodeEditorInstance | null, columnName: string): void {
    const selection = editor?.getSelection()
    if (!editor || !selection) {
        return
    }
    editor.executeEdits('data-quality-output-schema', [
        {
            range: selection,
            text: escapePropertyAsHogQLIdentifier(columnName),
            forceMoveMarkers: true,
        },
    ])
    editor.focus()
}
