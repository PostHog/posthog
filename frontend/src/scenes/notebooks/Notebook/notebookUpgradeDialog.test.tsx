import { render } from '@testing-library/react'
import { createElement, Fragment } from 'react'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { CommentType } from '~/types'

import { NotebookNodeType } from '../types'
import { getMarkdownNotebookMarkdown, isMarkdownNotebookContent } from './markdownNotebookV2'
import { buildCommentRepliesByMarkId, openUpgradeToMarkdownNotebookDialog } from './notebookUpgradeDialog'

jest.mock('lib/lemon-ui/LemonDialog', () => ({
    LemonDialog: {
        open: jest.fn(),
    },
}))

const openDialogMock = LemonDialog.open as jest.Mock

describe('notebookUpgradeDialog', () => {
    beforeEach(() => {
        openDialogMock.mockClear()
    })

    it('warns before converting a notebook to markdown content', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Activation' }],
                },
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: { kind: 'TrendsQuery', series: [] },
                        },
                    },
                },
            ],
        }
        const setLocalContent = jest.fn()

        openUpgradeToMarkdownNotebookDialog({ content, setLocalContent })

        expect(openDialogMock).toHaveBeenCalledTimes(1)
        const dialogProps = openDialogMock.mock.calls[0][0]

        expect(dialogProps.title).toEqual('Convert this notebook to Markdown notebooks?')
        expect(dialogProps.primaryButton.children).toEqual('Convert to Markdown notebooks')
        expect(dialogProps.secondaryButton.children).toEqual('Cancel')

        const { getByText } = render(createElement(Fragment, null, dialogProps.content))

        expect(getByText(/This conversion only works one way/)).toBeInstanceOf(HTMLElement)
        expect(getByText('Make sure you want to continue before converting it.')).toBeInstanceOf(HTMLElement)

        dialogProps.primaryButton.onClick()

        expect(setLocalContent).toHaveBeenCalledTimes(1)
        const convertedContent = setLocalContent.mock.calls[0][0]
        expect(isMarkdownNotebookContent(convertedContent)).toBe(true)
        expect(getMarkdownNotebookMarkdown(convertedContent)).toEqual(`# Activation

<Query hideFilters query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />`)
    })

    it('embeds comment threads from range-anchored comments during conversion', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'annotated', marks: [{ type: 'comment', attrs: { id: 'mark-1' } }] },
                    ],
                },
            ],
        }
        const comments = [
            makeComment({ id: 'c1', content: 'Root note', item_context: { type: 'mark', id: 'mark-1' } }),
            makeComment({ id: 'c2', content: 'A reply', source_comment: 'c1', created_at: '2026-01-02T00:00:00Z' }),
            makeComment({ id: 'c3', content: '👍', source_comment: 'c1', item_context: { is_emoji: true } }),
            makeComment({ id: 'c4', content: 'Unanchored', item_context: null }),
        ]
        const setLocalContent = jest.fn()

        openUpgradeToMarkdownNotebookDialog({ content, comments, setLocalContent })
        openDialogMock.mock.calls[0][0].primaryButton.onClick()

        const markdown = getMarkdownNotebookMarkdown(setLocalContent.mock.calls[0][0])
        expect(markdown).toContain('<ref id="mark-1">annotated</ref>')
        expect(markdown).toContain('<Comment ref="mark-1"')
        expect(markdown).toContain('Root note')
        expect(markdown).toContain('A reply')
        expect(markdown).not.toContain('👍')
        expect(markdown).not.toContain('Unanchored')
    })

    it('groups comment threads by mark id, oldest first, skipping deleted comments', () => {
        const replies = buildCommentRepliesByMarkId([
            makeComment({ id: 'c1', content: 'Root', item_context: { type: 'mark', id: 'm1' } }),
            makeComment({ id: 'c2', content: 'Newer reply', source_comment: 'c1', created_at: '2026-01-03T00:00:00Z' }),
            makeComment({ id: 'c3', content: 'Older reply', source_comment: 'c1', created_at: '2026-01-02T00:00:00Z' }),
            makeComment({ id: 'c4', content: 'Gone', source_comment: 'c1', deleted: true }),
        ])

        expect(replies['m1'].map((reply) => (reply as { text: string }).text)).toEqual([
            'Root',
            'Older reply',
            'Newer reply',
        ])
    })
})

function makeComment(overrides: Partial<CommentType>): CommentType {
    return {
        id: 'comment-id',
        content: null,
        rich_content: null,
        version: 0,
        created_at: '2026-01-01T00:00:00Z',
        created_by: {
            id: 1,
            uuid: 'user-uuid',
            distinct_id: 'user-distinct-id',
            first_name: 'Ann',
            email: 'ann@example.com',
        },
        scope: 'Notebook',
        item_context: null,
        is_task: false,
        completed_at: null,
        completed_by: null,
        ...overrides,
    }
}
