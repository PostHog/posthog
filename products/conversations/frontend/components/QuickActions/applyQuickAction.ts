import { JSONContent } from '@tiptap/core'
import { Editor } from '@tiptap/react'

import { EditorRange } from 'lib/components/RichContentEditor/types'

import type { QuickActionActionsApi, QuickActionApi } from '../../generated/api.schemas'
import { QuickActionKindEnumApi } from '../../generated/api.schemas'
import { applyTemplateVariablesToRichContent, TemplateVariableValues } from '../Editor/templateVariables'

/** True if the TipTap tree contains any non-empty text node or a media node worth rendering. */
function hasVisibleText(node: JSONContent): boolean {
    if (typeof node.text === 'string' && node.text.length > 0) {
        return true
    }
    if (node.type === 'image') {
        return true
    }
    return Array.isArray(node.content) && node.content.some(hasVisibleText)
}

/**
 * Build the TipTap document for a response quick action. Prefers the stored `rich_content`, falling
 * back to the plain-text `content` (one paragraph per line) so quick actions created without rich
 * content — e.g. via the API — still render in the editor instead of appearing blank.
 */
export function quickActionToDoc(quickAction: QuickActionApi): JSONContent {
    const richContent = quickAction.rich_content as JSONContent | undefined
    // Require an actual text node, not just a non-empty content array: the canonical "empty"
    // TipTap doc is `{doc:[{paragraph:[]}]}` (length 1) and would otherwise pass and render blank,
    // masking the plain-text `content` fallback below.
    if (richContent && richContent.type === 'doc' && hasVisibleText(richContent)) {
        return richContent
    }
    const text = quickAction.content ?? ''
    const paragraphs: JSONContent[] = text
        ? text.split('\n').map((line) => ({ type: 'paragraph', content: line ? [{ type: 'text', text: line }] : [] }))
        : [{ type: 'paragraph', content: [] }]
    return { type: 'doc', content: paragraphs }
}

/** Build the TipTap nodes to insert, with {{variables}} already substituted. */
function buildInsertContent(quickAction: QuickActionApi, variables: TemplateVariableValues): JSONContent[] {
    const doc = applyTemplateVariablesToRichContent(quickActionToDoc(quickAction), variables)
    return doc.content ?? [{ type: 'paragraph', content: [] }]
}

export interface ApplyQuickActionOptions {
    /** Values used to fill {{variable}} tokens in the response body. */
    variables?: TemplateVariableValues
    /** When set (slash-command flow), the trigger text is replaced; otherwise content is inserted at the cursor. */
    range?: EditorRange
    /** Applies the quick action's ticket actions (status/assignee/tags/priority). No-op when empty. */
    onApplyActions?: (actions: QuickActionActionsApi) => void
}

/** Insert a response quick action's body into the editor and apply its ticket actions, if any. */
export function applyQuickActionToEditor(
    editor: Editor,
    quickAction: QuickActionApi,
    options: ApplyQuickActionOptions = {}
): void {
    const content = buildInsertContent(quickAction, options.variables ?? {})
    const chain = editor.chain().focus()
    if (options.range) {
        chain.deleteRange(options.range).insertContentAt(options.range.from, content).run()
    } else {
        chain.insertContent(content).run()
    }
    if (quickAction.actions && Object.keys(quickAction.actions).length > 0) {
        options.onApplyActions?.(quickAction.actions)
    }
}

export interface RunOrInsertOptions extends ApplyQuickActionOptions {
    /** Called for workflow-kind quick actions instead of inserting text. */
    onRunWorkflow?: (quickAction: QuickActionApi) => void
}

/** Dispatch a chosen quick action by kind: workflow kind runs, response kind inserts its body. */
export function runOrInsertQuickAction(editor: Editor, quickAction: QuickActionApi, options: RunOrInsertOptions): void {
    if (quickAction.kind === QuickActionKindEnumApi.Workflow) {
        // Remove the "/query" trigger text (slash flow) — a workflow inserts nothing.
        if (options.range) {
            editor.chain().focus().deleteRange(options.range).run()
        }
        options.onRunWorkflow?.(quickAction)
        return
    }
    applyQuickActionToEditor(editor, quickAction, options)
}
