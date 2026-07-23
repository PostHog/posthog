import { JSONContent } from '@tiptap/core'
import { Editor } from '@tiptap/react'

import { EditorRange, RichContentNodeType } from 'lib/components/RichContentEditor/types'

import type { QuickActionActionsApi, QuickActionApi } from '../../generated/api.schemas'
import { applyTemplateVariablesToRichContent, TemplateVariableValues } from '../Editor/templateVariables'

// Leaf/atom nodes that carry content even though they have no child text (image, @mention).
const CONTENT_LEAF_TYPES = new Set([RichContentNodeType.Mention, 'image'])

/** True if the TipTap tree contains any non-empty text node or a content-bearing leaf node. */
export function hasVisibleText(node: JSONContent): boolean {
    if (typeof node.text === 'string' && node.text.length > 0) {
        return true
    }
    if (node.type && CONTENT_LEAF_TYPES.has(node.type)) {
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

/** True if the quick action has a reply worth inserting (rich content with text, or plain content). */
export function quickActionHasReply(quickAction: QuickActionApi): boolean {
    const richContent = quickAction.rich_content as JSONContent | undefined
    if (richContent && richContent.type === 'doc' && hasVisibleText(richContent)) {
        return true
    }
    return !!quickAction.content
}

export interface ApplyOptions extends ApplyQuickActionOptions {
    /** Runs the quick action's workflow, if it has one. */
    onRunWorkflow?: (quickAction: QuickActionApi) => void
}

/**
 * Apply a chosen quick action: insert its reply (if any) and apply ticket actions, then run its
 * workflow (if any). Any combination is valid — a quick action can reply, run a workflow, or both.
 */
export function applyQuickAction(editor: Editor, quickAction: QuickActionApi, options: ApplyOptions): void {
    if (quickActionHasReply(quickAction)) {
        applyQuickActionToEditor(editor, quickAction, options)
    } else {
        // Nothing to insert (workflow-only): still apply ticket actions and clear the "/query" text.
        if (options.range) {
            editor.chain().focus().deleteRange(options.range).run()
        }
        if (quickAction.actions && Object.keys(quickAction.actions).length > 0) {
            options.onApplyActions?.(quickAction.actions)
        }
    }
    if (quickAction.workflow_id) {
        options.onRunWorkflow?.(quickAction)
    }
}
