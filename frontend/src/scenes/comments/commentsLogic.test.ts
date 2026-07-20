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
})
