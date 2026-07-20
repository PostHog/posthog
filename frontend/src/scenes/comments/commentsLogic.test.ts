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
            composerDraft: DRAFT_CONTENT,
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

    it('creates a reply against the thread root, clears the draft and does not scroll to the bottom', async () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')
        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
        })
            .toDispatchActions(['sendComposedContentSuccess'])
            .toNotHaveDispatchedActions([sidePanelDiscussionLogic.actionTypes.scrollToLastComment])
            .toMatchValues({ replyingCommentId: null, composerDraft: null })
        expect(lastCreateBody?.source_comment).toBe('thread-1')
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
        expect(logic.values.composerDraft).toEqual(DRAFT_CONTENT)
    })

    it('keeps a replied-to thread expanded after the reply is sent', async () => {
        logic.actions.setRichContentEditor(createEditor(DRAFT_CONTENT))
        logic.actions.setReplyingComment('thread-1')
        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.sendComposedContent(false)
        }).toDispatchActions(['sendComposedContentSuccess'])

        // Pinned open when the reply started, so the just-sent reply stays visible
        expect(logic.values.replyingCommentId).toBeNull()
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

    it('expands the thread containing a deep-linked reply', async () => {
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

        logic.actions.setSelectedComment('reply-1')

        expect(logic.values.expandedThreadIds.has('thread-1')).toBe(true)
    })
})
