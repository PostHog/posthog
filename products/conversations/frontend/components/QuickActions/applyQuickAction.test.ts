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

/** Minimal chainable editor stub that records whether insert methods were called. */
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

    // Regression: the dispatcher inserts a reply when the quick action has one; an actions-only
    // quick action applies its ticket actions without inserting any text.
    describe('applyQuickAction', () => {
        it("inserts a reply quick action's body", () => {
            const { editor, state } = fakeEditor()

            applyQuickAction(editor, quickAction({ content: 'hello' }), {})

            expect(state.insertedContent).toBe(true)
        })

        it('applies ticket actions without inserting for an actions-only quick action', () => {
            const { editor, state } = fakeEditor()
            const onApplyActions = jest.fn()
            const actionsOnly = quickAction({ actions: { tags: ['vip'] } })

            applyQuickAction(editor, actionsOnly, { onApplyActions })

            expect(state.insertedContent).toBe(false)
            expect(onApplyActions).toHaveBeenCalledWith({ tags: ['vip'] })
        })
    })
})
