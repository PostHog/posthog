import { JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'

import {
    SUPPORT_EXTENSIONS,
    SUPPORT_GREETING_EXTENSIONS,
    SUPPORT_PREVIEW_EXTENSIONS,
    serializeToMarkdown,
    serializeToPlainText,
} from './SupportEditor'

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
    ])('serializeToMarkdown handles %s', (_name, doc, expected) => {
        expect(serializeToMarkdown(doc)).toBe(expected)
    })

    // The widget greeting keeps a plain-text fallback for widgets that predate the rich-content key.
    // That field must stay free of markdown escapes and link syntax, or the widget shows them literally.
    const link = (text: string, href: string): JSONContent => ({
        type: 'text',
        text,
        marks: [{ type: 'link', attrs: { href } }],
    })
    test.each<[string, JSONContent, string]>([
        [
            'punctuation without markdown escapes',
            { type: 'doc', content: [paragraph('Hi there! We can help.')] },
            'Hi there! We can help.',
        ],
        [
            'a link as label plus destination',
            {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [{ type: 'text', text: 'Check our ' }, link('FAQ', 'https://example.com/faq')],
                    },
                ],
            },
            'Check our FAQ (https://example.com/faq)',
        ],
        [
            'a bare url link without duplication',
            {
                type: 'doc',
                content: [{ type: 'paragraph', content: [link('https://example.com/faq', 'https://example.com/faq')] }],
            },
            'https://example.com/faq',
        ],
        [
            'formatting marks dropped',
            {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'bold', marks: [{ type: 'bold' }] }] }],
            },
            'bold',
        ],
    ])('serializeToPlainText renders %s', (_name, doc, expected) => {
        expect(serializeToPlainText(doc)).toBe(expected)
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

    // The greeting is served in the unauthenticated per-token config every site visitor receives.
    // A member mention there would publish an internal user ID, so the greeting editor drops mentions.
    it('greeting schema has no mention node, unlike the full editor', () => {
        const mentionDoc: JSONContent = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'ph-mention', attrs: { id: 7 } }] }],
        }
        // The full editor keeps mentions for internal agent threads.
        expect(() => ProseMirrorNode.fromJSON(getSchema([...SUPPORT_EXTENSIONS]), mentionDoc).check()).not.toThrow()
        // The public greeting must not, or `@member:<id>` leaks into the widget config.
        expect(() => ProseMirrorNode.fromJSON(getSchema([...SUPPORT_GREETING_EXTENSIONS]), mentionDoc)).toThrow(
            'Unknown node type: ph-mention'
        )
    })
})
