import { JSONContent } from 'lib/components/RichContentEditor/types'

import { getCommentText } from './commentUtils'

describe('getCommentText', () => {
    // DEFAULT_EXTENSIONS keeps no marks and only paragraph/mention nodes, but conversations authors
    // comments with a richer schema. Each of these used to throw "There is no mark/node type ... in
    // this schema" out of generateText and crash the ticket thread. The fallback must return the text.
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
