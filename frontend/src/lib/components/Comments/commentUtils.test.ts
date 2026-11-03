import { JSONContent } from 'lib/components/RichContentEditor/types'

import { getCommentText, isLinkedSlackThread } from './commentUtils'

describe('getCommentText', () => {
    // Each shape here carries a mark or node DEFAULT_EXTENSIONS lacks, which used to throw out of
    // generateText and crash the ticket thread. The fallback must return readable text instead.
    it.each([
        [
            'italic mark',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            { type: 'text', text: 'plain ' },
                            { type: 'text', text: 'emphasis', marks: [{ type: 'italic' }] },
                        ],
                    },
                ],
            },
            'plain emphasis',
        ],
        [
            'bullet list node',
            {
                type: 'doc',
                content: [
                    {
                        type: 'bulletList',
                        content: [
                            {
                                type: 'listItem',
                                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'one' }] }],
                            },
                            {
                                type: 'listItem',
                                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'two' }] }],
                            },
                        ],
                    },
                ],
            },
            'one\n\ntwo',
        ],
        [
            'image node',
            {
                type: 'doc',
                content: [
                    { type: 'paragraph', content: [{ type: 'text', text: 'see', marks: [{ type: 'italic' }] }] },
                    { type: 'image', attrs: { src: 'https://example.com/a.png', alt: 'a' } },
                ],
            },
            'see\n\n![a](https://example.com/a.png)',
        ],
        [
            'id-less mention',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            { type: 'text', text: 'hi ', marks: [{ type: 'bold' }] },
                            { type: 'ph-mention', attrs: {} },
                        ],
                    },
                ],
            },
            'hi ',
        ],
    ])('renders %s content without throwing', (_label, richContent, expected) => {
        expect(getCommentText({ rich_content: richContent as JSONContent })).toBe(expected)
    })

    it('serializes a mention through the fallback', () => {
        const richContent: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'hey ', marks: [{ type: 'bold' }] },
                        { type: 'ph-mention', attrs: { id: 42 } },
                    ],
                },
            ],
        }
        expect(getCommentText({ rich_content: richContent })).toBe('hey @member:42')
    })
})

describe('isLinkedSlackThread', () => {
    const SLACK_THREAD = { channel_id: 'C0123ABCDEF', channel_name: 'team-exports', url: 'https://slack.test/t' }

    // Only a thread brought in from Slack can be unlinked. One written here and sent to Slack, or a
    // reply that synced in from Slack, shares some of its fields and must not count.
    it.each([
        [
            'an opening comment linked from Slack',
            { item_context: { from_slack: true }, slack_thread: SLACK_THREAD },
            true,
        ],
        ['an opening comment sent to Slack from here', { item_context: null, slack_thread: SLACK_THREAD }, false],
        ['a reply that synced in from Slack', { source_comment: 'root', item_context: { from_slack: true } }, false],
        ['an opening comment from Slack whose sync was removed', { item_context: { from_slack: true } }, false],
    ])('%s: %s', (_, comment, expected) => {
        expect(isLinkedSlackThread({ source_comment: null, slack_thread: null, ...comment })).toBe(expected)
    })
})
