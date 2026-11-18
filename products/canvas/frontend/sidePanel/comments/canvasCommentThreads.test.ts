import type { CommentType } from '~/types'

import {
    buildCanvasCommentThreads,
    canvasCommentHighlights,
    canvasTextAnchor,
    translateCanvasTextSelection,
} from './canvasCommentThreads'

const ANCHOR = { kind: 'text', quote: 'Signups', prefix: '', suffix: ' this week', start: 0, end: 7 }

function comment(overrides: Partial<CommentType> & { id: string; created_at: string }): CommentType {
    return {
        content: 'A comment',
        rich_content: null,
        version: 0,
        created_by: null,
        source_comment: null,
        scope: 'canvas',
        item_id: 'canvas-1',
        item_context: null,
        is_task: false,
        completed_at: null,
        completed_by: null,
        ...overrides,
    }
}

describe('canvas comment threads', () => {
    it('stores only the quoted text the viewer can review', () => {
        expect(
            canvasTextAnchor({
                quote: 'Signups',
                prefix: 'private viewer state',
                suffix: 'private connector result',
                start: 123456,
                end: 123463,
                rect: { top: 10, right: 50, bottom: 20, left: 5 },
            })
        ).toEqual({ kind: 'text', quote: 'Signups', prefix: '', suffix: '', start: 0, end: 7 })
    })

    it.each([
        { name: 'open without state replies', states: [], expected: false },
        { name: 'resolved by a resolve reply', states: ['resolved'], expected: true },
        { name: 'open again after a reopen reply', states: ['resolved', 'open'], expected: false },
    ])('reads a thread as $name', ({ states, expected }) => {
        const root = comment({ id: 'root', created_at: '2026-01-01T00:00:00Z', item_context: { anchor: ANCHOR } })
        const replies = states.map((threadState, index) =>
            comment({
                id: `state-${index}`,
                created_at: `2026-01-01T00:0${index + 1}:00Z`,
                source_comment: 'root',
                item_context: { anchor: ANCHOR, threadState },
            })
        )
        // Replies arrive newest first from the API, so the grouping must not trust the input order.
        const [thread] = buildCanvasCommentThreads([...replies].reverse().concat(root))
        expect(thread.resolved).toBe(expected)
        expect(thread.replies.map((reply) => reply.id)).toEqual(replies.map((reply) => reply.id))
    })

    it('highlights only open text threads written on the version on screen', () => {
        const threads = buildCanvasCommentThreads([
            comment({
                id: 'on-v2',
                created_at: '2026-01-01T00:00:00Z',
                item_context: { anchor: ANCHOR, canvasVersionId: 'v2' },
            }),
            comment({
                id: 'on-v1',
                created_at: '2026-01-01T00:01:00Z',
                item_context: { anchor: ANCHOR, canvasVersionId: 'v1' },
            }),
            comment({ id: 'no-version', created_at: '2026-01-01T00:02:00Z', item_context: { anchor: ANCHOR } }),
            comment({ id: 'no-anchor', created_at: '2026-01-01T00:03:00Z', item_context: {} }),
            comment({
                id: 'resolved',
                created_at: '2026-01-01T00:04:00Z',
                item_context: { anchor: ANCHOR },
                completed_at: '2026-01-02T00:00:00Z',
            }),
            comment({
                id: 'bad-range',
                created_at: '2026-01-01T00:05:00Z',
                item_context: { anchor: { ...ANCHOR, end: 0 } },
            }),
        ])
        expect(canvasCommentHighlights(threads, 'v2', 'no-version')).toEqual([
            { id: 'on-v2', active: false, anchor: ANCHOR },
            { id: 'no-version', active: true, anchor: ANCHOR },
        ])
    })

    it('moves a selection rect from frame coordinates into page coordinates', () => {
        const selection = { ...ANCHOR, rect: { top: 10, right: 50, bottom: 20, left: 5 } }
        expect(translateCanvasTextSelection(selection, { left: 300, top: 48 }).rect).toEqual({
            top: 58,
            right: 350,
            bottom: 68,
            left: 305,
        })
        expect(translateCanvasTextSelection(selection, null).rect).toEqual(selection.rect)
    })
})
