import { JSONContent } from '@tiptap/core'
import { Editor } from '@tiptap/react'

import { EditorRange } from 'lib/components/RichContentEditor/types'

import type { MacroActionsApi, MacroApi } from '../../generated/api.schemas'
import { applyMacroVariablesToRichContent, MacroVariableValues } from '../Editor/macroVariables'

/**
 * Build the TipTap document for a macro. Prefers the stored `rich_content`, falling back to the
 * plain-text `content` (one paragraph per line) so macros created without rich content — e.g. via
 * the API — still render in the editor instead of appearing blank.
 */
export function macroToDoc(macro: MacroApi): JSONContent {
    const richContent = macro.rich_content as JSONContent | undefined
    if (richContent && richContent.type === 'doc' && Array.isArray(richContent.content) && richContent.content.length) {
        return richContent
    }
    const text = macro.content ?? ''
    const paragraphs: JSONContent[] = text
        ? text.split('\n').map((line) => ({ type: 'paragraph', content: line ? [{ type: 'text', text: line }] : [] }))
        : [{ type: 'paragraph', content: [] }]
    return { type: 'doc', content: paragraphs }
}

/** Build the TipTap nodes to insert for a macro, with {{variables}} already substituted. */
function buildInsertContent(macro: MacroApi, variables: MacroVariableValues): JSONContent[] {
    const doc = applyMacroVariablesToRichContent(macroToDoc(macro), variables)
    return doc.content ?? [{ type: 'paragraph', content: [] }]
}

export interface ApplyMacroOptions {
    /** Values used to fill {{variable}} tokens in the macro body. */
    variables?: MacroVariableValues
    /** When set (slash-command flow), the trigger text is replaced; otherwise content is inserted at the cursor. */
    range?: EditorRange
    /** Applies the macro's ticket actions (status/assignee/tags/priority). No-op for text-only macros. */
    onApplyActions?: (actions: MacroActionsApi) => void
}

/** Insert a macro's body into the editor and apply its ticket actions, if any. */
export function applyMacroToEditor(editor: Editor, macro: MacroApi, options: ApplyMacroOptions = {}): void {
    const content = buildInsertContent(macro, options.variables ?? {})
    const chain = editor.chain().focus()
    if (options.range) {
        chain.deleteRange(options.range).insertContentAt(options.range.from, content).run()
    } else {
        chain.insertContent(content).run()
    }
    if (macro.actions && Object.keys(macro.actions).length > 0) {
        options.onApplyActions?.(macro.actions)
    }
}
