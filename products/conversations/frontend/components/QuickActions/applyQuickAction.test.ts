import { Editor } from '@tiptap/react'

import type { QuickActionApi } from '../../generated/api.schemas'
import { applyQuickAction, quickActionToDoc } from './applyQuickAction'

function quickAction(overrides: Partial<QuickActionApi>): QuickActionApi {
    return {
        id: '1',
        short_id: 'abc',
        name: 'Test',
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

    // Regression: a quick action applies whatever it has. Workflow-only runs without inserting;
    // reply-only inserts without running; a quick action with both does both.
    describe('applyQuickAction', () => {
        it('runs a workflow-only quick action without inserting text', () => {
            const { editor, state } = fakeEditor()
            const onRunWorkflow = jest.fn()
            const wf = quickAction({ workflow_id: 'w1' })

            applyQuickAction(editor, wf, { onRunWorkflow })

            expect(onRunWorkflow).toHaveBeenCalledWith(wf)
            expect(state.insertedContent).toBe(false)
        })

        it('inserts a reply-only quick action without running a workflow', () => {
            const { editor, state } = fakeEditor()
            const onRunWorkflow = jest.fn()
            const resp = quickAction({ content: 'hello' })

            applyQuickAction(editor, resp, { onRunWorkflow })

            expect(onRunWorkflow).not.toHaveBeenCalled()
            expect(state.insertedContent).toBe(true)
        })

        it('both inserts the reply and runs the workflow when the quick action has both', () => {
            const { editor, state } = fakeEditor()
            const onRunWorkflow = jest.fn()
            const both = quickAction({ content: 'generating that for you', workflow_id: 'w1' })

            applyQuickAction(editor, both, { onRunWorkflow })

            expect(state.insertedContent).toBe(true)
            expect(onRunWorkflow).toHaveBeenCalledWith(both)
        })
    })
})
