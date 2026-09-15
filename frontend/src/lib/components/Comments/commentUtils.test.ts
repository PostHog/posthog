import { JSONContent } from 'lib/components/RichContentEditor/types'

import { getCommentText } from './commentUtils'

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
