import { Editor } from '@tiptap/react'

import type { QuickActionApi } from '../../generated/api.schemas'
import { QuickActionKindEnumApi } from '../../generated/api.schemas'
import { quickActionToDoc, runOrInsertQuickAction } from './applyQuickAction'

function quickAction(overrides: Partial<QuickActionApi>): QuickActionApi {
    return {
        id: '1',
        short_id: 'abc',
        name: 'Test',
        kind: QuickActionKindEnumApi.Response,
        created_at: '2026-01-01T00:00:00Z',
        created_by: {} as QuickActionApi['created_by'],
        ...overrides,
    }
}

/** Minimal chainable editor stub — records whether insert methods were called. */
function fakeEditor(): { editor: Editor; state: { insertedContent: boolean } } {
    const state = { insertedContent: false }
    const chain: any = {
        focus: () => chain,
        deleteRange: () => chain,
        insertContentAt: () => {
            state.insertedContent = true
            return chain
        },
        insertContent: () => {
            state.insertedContent = true
            return chain
        },
        run: () => true,
    }
    return { editor: { chain: () => chain } as unknown as Editor, state }
}

describe('applyQuickAction', () => {
    describe('quickActionToDoc', () => {
        it('uses stored rich_content when present', () => {
            const rich = {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'rich body' }] }],
            }
            expect(quickActionToDoc(quickAction({ rich_content: rich, content: 'plain fallback' }))).toEqual(rich)
        })

        // Regression: quick actions created via the API (or imported) have only plain-text `content`
        // and no rich_content. Without this fallback the editor renders blank and saving wipes it.
        it('falls back to plain-text content, one paragraph per line', () => {
            const doc = quickActionToDoc(quickAction({ rich_content: {}, content: 'line one\nline two' }))
            expect(doc).toEqual({
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'line one' }] },
                    { type: 'paragraph', content: [{ type: 'text', text: 'line two' }] },
                ],
            })
        })

        // The canonical empty TipTap doc has a one-paragraph content array; it must not be treated as
        // real rich content, or it would render blank and mask the plain-text fallback.
        it('treats an empty rich_content doc as blank and falls back to content', () => {
            const emptyDoc = { type: 'doc', content: [{ type: 'paragraph', content: [] }] }
            const doc = quickActionToDoc(quickAction({ rich_content: emptyDoc, content: 'from content' }))
            expect(doc).toEqual({
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'from content' }] }],
            })
        })

        it('returns an empty paragraph when there is no content at all', () => {
            expect(quickActionToDoc(quickAction({ rich_content: {}, content: '' }))).toEqual({
                type: 'doc',
                content: [{ type: 'paragraph', content: [] }],
            })
        })
    })

    // Regression: the kind dispatch must not cross wires — a workflow must run (not insert text or
    // fire ticket actions), and a response must insert (not trigger a workflow run).
    describe('runOrInsertQuickAction', () => {
        it('runs a workflow quick action without inserting text', () => {
            const { editor, state } = fakeEditor()
            const onRunWorkflow = jest.fn()
            const onApplyActions = jest.fn()
            const wf = quickAction({ kind: QuickActionKindEnumApi.Workflow, workflow_id: 'w1' })

            runOrInsertQuickAction(editor, wf, { onRunWorkflow, onApplyActions })

            expect(onRunWorkflow).toHaveBeenCalledWith(wf)
            expect(onApplyActions).not.toHaveBeenCalled()
            expect(state.insertedContent).toBe(false)
        })

        it('inserts a response quick action without running a workflow', () => {
            const { editor, state } = fakeEditor()
            const onRunWorkflow = jest.fn()
            const resp = quickAction({ kind: QuickActionKindEnumApi.Response, content: 'hello' })

            runOrInsertQuickAction(editor, resp, { onRunWorkflow })

            expect(onRunWorkflow).not.toHaveBeenCalled()
            expect(state.insertedContent).toBe(true)
        })
    })
})
