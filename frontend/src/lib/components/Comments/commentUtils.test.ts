import { generateText } from '@tiptap/core'

import { DEFAULT_EXTENSIONS, serializationOptions } from 'lib/components/RichContentEditor/LemonRichContentEditor'
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

    const paragraph = (...content: JSONContent[]): JSONContent => ({ type: 'paragraph', content })
    const text = (value: string): JSONContent => ({ type: 'text', text: value })

    // Comments render their text without the editor, so text from the comment schema must match what the editor extracts.
    it.each<[string, JSONContent[]]>([
        ['one paragraph', [paragraph(text('hello'))]],
        ['two paragraphs', [paragraph(text('first')), paragraph(text('second'))]],
        ['an empty paragraph between two', [paragraph(text('first')), paragraph(), paragraph(text('second'))]],
        ['a mention', [paragraph(text('hey '), { type: 'ph-mention', attrs: { id: 42 } }, text(' look'))]],
        ['an empty document', [paragraph()]],
    ])('extracts the same text as the editor from %s', (_label, content) => {
        const richContent: JSONContent = { type: 'doc', content }

        expect(getCommentText({ rich_content: richContent })).toBe(
            generateText(richContent, DEFAULT_EXTENSIONS, serializationOptions)
        )
    })
})
