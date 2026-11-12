import { JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'

import { SUPPORT_PREVIEW_EXTENSIONS, serializeToMarkdown } from './SupportEditor'

// jest.setup.ts stubs this module out, which would make schema construction meaningless here
jest.unmock('@tiptap/extension-code-block-lowlight')

const paragraph = (text: string): JSONContent => ({ type: 'paragraph', content: [{ type: 'text', text }] })
const listItem = (...content: JSONContent[]): JSONContent => ({ type: 'listItem', content })

describe('SupportEditor serialization and preview schema', () => {
    // The widget renders only the plain-text field, so anything dropped here is
    // invisible to widget-only customers.
    test.each<[string, JSONContent, string]>([
        [
            'bullet list',
            {
                type: 'doc',
                content: [{ type: 'bulletList', content: [listItem(paragraph('one')), listItem(paragraph('two'))] }],
            },
            '- one\n- two',
        ],
        [
            'ordered list respecting start',
            {
                type: 'doc',
                content: [
                    {
                        type: 'orderedList',
                        attrs: { start: 3 },
                        content: [listItem(paragraph('three')), listItem(paragraph('four'))],
                    },
                ],
            },
            '3. three\n4. four',
        ],
        [
            'nested list indented under its parent item',
            {
                type: 'doc',
                content: [
                    {
                        type: 'orderedList',
                        content: [
                            listItem(paragraph('parent'), {
                                type: 'bulletList',
                                content: [listItem(paragraph('child'))],
                            }),
                        ],
                    },
                ],
            },
            '1. parent\n   - child',
        ],
        [
            'list followed by paragraph and image keeps all blocks',
            {
                type: 'doc',
                content: [
                    { type: 'bulletList', content: [listItem(paragraph('item'))] },
                    { type: 'image', attrs: { src: 'https://example.com/cat.png', alt: 'cat' } },
                ],
            },
            '- item\n\n![cat](https://example.com/cat.png)',
        ],
        [
            'prose punctuation left unescaped, inline formatting characters escaped',
            {
                type: 'doc',
                content: [
                    paragraph('Thanks! See v1.2-rc (#81525): distinct_id café_été __dunder__ end_ _emph_ *c* [d] `e`'),
                ],
            },
            'Thanks! See v1.2-rc (#81525): distinct_id café_été \\_\\_dunder\\_\\_ end\\_ \\_emph\\_ \\*c\\* \\[d\\] \\`e\\`',
        ],
        [
            'block markers escaped only at line start',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            { type: 'text', text: 'Thanks' },
                            { type: 'hardBreak' },
                            { type: 'text', text: '---' },
                            { type: 'hardBreak' },
                            { type: 'text', text: '- Eleftheria' },
                            { type: 'hardBreak' },
                            { type: 'text', text: '1. not a list, 2 - 1 = 1 and #81525' },
                        ],
                    },
                ],
            },
            'Thanks  \n\\---  \n\\- Eleftheria  \n1\\. not a list, 2 - 1 = 1 and #81525',
        ],
    ])('serializeToMarkdown handles %s', (_name, doc, expected) => {
        expect(serializeToMarkdown(doc)).toBe(expected)
    })

    it('preview schema accepts docs authored with the full HogDesk node set', () => {
        const hogdeskDoc: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'paragraph',
                    content: [
                        { type: 'text', text: 'Hey,' },
                        { type: 'hardBreak' },
                        { type: 'text', text: 'crossed out', marks: [{ type: 'strike' }] },
                    ],
                },
                { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Options' }] },
                {
                    type: 'orderedList',
                    attrs: { type: null, start: 1 },
                    content: [listItem(paragraph('first')), listItem(paragraph('second'))],
                },
                { type: 'blockquote', content: [paragraph('quoted')] },
                { type: 'horizontalRule' },
                {
                    type: 'image',
                    attrs: { src: 'https://example.com/a.png', alt: null, title: null, width: 100, height: 50 },
                },
            ],
        }
        const schema = getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        expect(() => ProseMirrorNode.fromJSON(schema, hogdeskDoc).check()).not.toThrow()
    })

    it('preview schema rejects unknown node types so the plain-content fallback kicks in', () => {
        const doc: JSONContent = { type: 'doc', content: [{ type: 'table', content: [] }] }
        const schema = getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        expect(() => ProseMirrorNode.fromJSON(schema, doc)).toThrow('Unknown node type: table')
    })
})
