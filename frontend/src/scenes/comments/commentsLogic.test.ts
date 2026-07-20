import { expectLogic } from 'kea-test-utils'

import { JSONContent, RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { commentsLogic } from './commentsLogic'

const DRAFT_CONTENT: JSONContent = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'draft' }] }],
}

const makeComment = (id: string, sourceComment: string | null = null): Record<string, any> => ({
    id,
    content: id,
    rich_content: null,
    version: 0,
    created_at: '2025-10-08T10:00:00.000Z',
    created_by: null,
    source_comment: sourceComment,
    scope: 'Insight',
    item_id: '1',
    item_context: null,
    is_task: false,
    completed_at: null,
    completed_by: null,
})

const createEditor = (content: JSONContent | null = null): RichContentEditorType =>
    ({
        isEmpty: () => content === null,
        getJSON: () => content,
        getMentions: () => [],
        focus: jest.fn(),
        clear: jest.fn(),
    }) as unknown as RichContentEditorType

describe('commentsLogic', () => {
    let logic: ReturnType<typeof commentsLogic.build>
    let lastCreateBody: Record<string, any> | null = null

    beforeEach(() => {
        lastCreateBody = null
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/comments': { results: [] },
                '/api/organizations/@current/members/': { results: [] },
            },
            post: {
                '/api/projects/:team_id/comments': async ({ request }) => {
                    lastCreateBody = (await request.json()) as Record<string, any>
                    return [
                        201,
                        {
                            ...lastCreateBody,
                            id: 'new-comment',
                            created_at: '2025-10-10T00:00:00.000Z',
                            created_by: null,
                            version: 0,
                        },
                    ]
                },
            },
        })
        logic = commentsLogic({ scope: ActivityScope.INSIGHT, item_id: '1' })
        logic.mount()
    })

    it('captures the composer draft when entering reply mode and clears the item context', async () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        await expectLogic(logic, () => {
            logic.actions.setItemContext({ type: 'mark', id: 'ctx' })
            logic.actions.setReplyingComment('thread-1')
        }).toMatchValues({
            composerDrafts: { footer: DRAFT_CONTENT },
            currentComposerDraft: null,
            replyingCommentId: 'thread-1',
            itemContext: null,
        })
        expect(logic.values.selectedCommentId).toBe('thread-1')
    })

    it('cancels an in-progress reply when an item context is set', async () => {
        logic.actions.setRichContentEditor(createEditor(null))
        await expectLogic(logic, () => {
            logic.actions.setReplyingComment('thread-1')
            logic.actions.setItemContext({ type: 'mark', id: 'ctx' })
        }).toMatchValues({
            replyingCommentId: null,
            itemContext: expect.objectContaining({ context: { type: 'mark', id: 'ctx' } }),
        })
    })

    it('only focuses a newly registered editor while a reply or item context is active', () => {
        const footerEditor = createEditor(null)
        logic.actions.setRichContentEditor(footerEditor)
        expect(footerEditor.focus).not.toHaveBeenCalled()

        logic.actions.setReplyingComment('thread-1')
        const inlineEditor = createEditor(null)
        logic.actions.setRichContentEditor(inlineEditor)
        expect(inlineEditor.focus).toHaveBeenCalledWith('end')
    })

    it('creates a reply against the thread root and keeps a cleared, focused composer open', async () => {
        const editor = createEditor(DRAFT_CONTENT)
        logic.actions.setRichContentEditor(editor)
        logic.actions.setReplyingComment('thread-1')
        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
        })
            .toDispatchActions(['sendComposedContentSuccess'])
            .toNotHaveDispatchedActions([sidePanelDiscussionLogic.actionTypes.scrollToLastComment])
            // Reply mode persists so the user can send a follow-up reply straight away
            .toMatchValues({ replyingCommentId: 'thread-1', currentComposerDraft: null })
        expect(lastCreateBody?.source_comment).toBe('thread-1')
        expect(editor.clear).toHaveBeenCalled()
        expect(editor.focus).toHaveBeenCalledWith('end')
    })

    it('scrolls to the bottom after sending a top-level comment', async () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
        }).toDispatchActions(['sendComposedContentSuccess', sidePanelDiscussionLogic.actionTypes.scrollToLastComment])
        expect(lastCreateBody?.source_comment).toBeUndefined()
    })

    it('clears reply mode when the reply target stops rendering after a reload', async () => {
        useMocks({ get: { '/api/projects/:team_id/comments': { results: [makeComment('thread-1')] } } })
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])

        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')
        expect(logic.values.replyingCommentId).toBe('thread-1')

        useMocks({ get: { '/api/projects/:team_id/comments': { results: [] } } })
        // The subscription dispatches the clear nested inside the reload dispatch, so
        // assert the resulting state rather than action order
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])

        expect(logic.values.replyingCommentId).toBeNull()
        expect(logic.values.composerDrafts['thread-1']).toEqual(DRAFT_CONTENT)
    })

    it('keeps a replied-to thread expanded after the reply flow ends', async () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
        }).toDispatchActions(['sendComposedContentSuccess'])

        // Pinned open when the reply started, so the sent reply stays visible even once
        // the user leaves reply mode
        logic.actions.setReplyingComment(null)
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)
    })

    it('lets a selected thread collapse but keeps the reply target open', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/comments': {
                    results: [makeComment('thread-1'), makeComment('reply-1', 'thread-1')],
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])

        // Selecting (clicking) a root comment must not block collapsing its thread
        logic.actions.setSelectedComment('thread-1')
        logic.actions.setThreadExpanded('thread-1', true)
        logic.actions.setThreadExpanded('thread-1', false)
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(false)

        // But the thread hosting the inline composer cannot be collapsed out from under it
        logic.actions.setRichContentEditor(createEditor(null))
        logic.actions.setReplyingComment('thread-1')
        logic.actions.setThreadExpanded('thread-1', false)
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)
    })

    it('startNewComment exits reply mode and focuses the footer composer once it registers', () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')

        logic.actions.startNewComment()
        expect(logic.values.replyingCommentId).toBeNull()
        // Deregistered so callers waiting for the footer editor never grab the outgoing one
        expect(logic.values.richContentEditor).toBeNull()

        const footerEditor = createEditor(null)
        logic.actions.setRichContentEditor(footerEditor)
        expect(footerEditor.focus).toHaveBeenCalledWith('end')

        // One-shot: an unrelated later remount must not steal focus
        const remountedEditor = createEditor(null)
        logic.actions.setRichContentEditor(remountedEditor)
        expect(remountedEditor.focus).not.toHaveBeenCalled()
    })

    it('expands the thread containing a deep-linked comment', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/comments': {
                    results: [makeComment('thread-1'), makeComment('reply-1', 'thread-1')],
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(false)

        // Deep link to a reply reveals its thread
        logic.actions.setSelectedComment('reply-1', true)
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)

        // Deep link to a thread root reveals its replies too
        logic.actions.setThreadExpanded('thread-1', false)
        logic.actions.setSelectedComment('thread-1', true)
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)
    })

    it('does not expand a thread when a comment is selected by clicking', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/comments': {
                    results: [makeComment('thread-1'), makeComment('reply-1', 'thread-1')],
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])

        // Clicking inside a comment (e.g. its emoji reaction button) selects it for the
        // highlight wash - that must not expand the collapsed thread
        logic.actions.setSelectedComment('thread-1')

        expect(logic.values.selectedCommentId).toBe('thread-1')
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(false)
    })

    it('reveals a deep-linked comment that was selected before comments loaded', async () => {
        // Deep link lands while comments are still loading - nothing to reveal yet
        logic.actions.setSelectedComment('reply-1', true)

        useMocks({
            get: {
                '/api/projects/:team_id/comments': {
                    results: [makeComment('thread-1'), makeComment('reply-1', 'thread-1')],
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])

        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)

        // The pending reveal is one-shot: collapsing and reloading must not re-expand
        logic.actions.setThreadExpanded('thread-1', false)
        await expectLogic(logic, () => {
            logic.actions.loadComments()
        }).toDispatchActions(['loadCommentsSuccess'])
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(false)
    })

    it('keeps a separate draft per thread', () => {
        const OTHER_DRAFT: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'other' }] }],
        }
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')

        // Simulate typing in thread-1's inline composer, then switching to thread-2
        logic.actions.setRichContentEditor(createEditor(OTHER_DRAFT))
        logic.actions.setReplyingComment('thread-2')

        // thread-1's text stays in its own slot instead of following into thread-2's composer
        expect(logic.values.composerDrafts['thread-1']).toEqual(OTHER_DRAFT)
        expect(logic.values.currentComposerDraft).toBeNull()

        // Returning to thread-1 restores its own draft
        logic.actions.setReplyingComment('thread-1')
        expect(logic.values.currentComposerDraft).toEqual(OTHER_DRAFT)
    })

    it('syncs isEmpty from the editor when a composer registers', () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        expect(logic.values.isEmpty).toBe(false)

        // A fresh empty composer replaces it (e.g. switching to a thread with no draft)
        logic.actions.setRichContentEditor(createEditor(null))
        expect(logic.values.isEmpty).toBe(true)

        // A composer seeded from a restored draft must enable sending straight away
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        expect(logic.values.isEmpty).toBe(false)
    })

    it('does not clear a composer that replaced the sender mid-flight', async () => {
        const replyEditor = createEditor(DRAFT_CONTENT)
        logic.actions.setRichContentEditor(replyEditor)
        logic.actions.setReplyingComment('thread-1')

        const footerEditor = createEditor(DRAFT_CONTENT)
        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
            // The user bails to a new comment while the POST is in flight
            logic.actions.startNewComment()
            logic.actions.setRichContentEditor(footerEditor)
        })
            .toDispatchActions(['sendComposedContentSuccess'])
            .toNotHaveDispatchedActions([sidePanelDiscussionLogic.actionTypes.scrollToLastComment])

        // The reply that sent is classified from send-time state, and the footer composer is untouched
        expect(footerEditor.clear).not.toHaveBeenCalled()
        expect(logic.values.composerDrafts['thread-1']).toBeNull()
    })
})
