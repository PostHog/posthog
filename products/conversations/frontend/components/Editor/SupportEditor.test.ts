import { JSONContent, getSchema } from '@tiptap/core'
import { DOMParser, Node as ProseMirrorNode } from '@tiptap/pm/model'

import { SUPPORT_EXTENSIONS, SUPPORT_PREVIEW_EXTENSIONS, serializeToMarkdown } from './SupportEditor'

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

    const SQL_LINES = ['WITH keyed AS (', '    SELECT uuid', '    FROM events', ')', 'SELECT * FROM keyed']
    const SQL = SQL_LINES.join('\n')

    // Only `content` reaches the server, so a pasted line that leaves the code block or is
    // dropped while parsing never arrives, even though the editor showed the full message.
    test.each<[string, string, string]>([
        ['newlines', `<pre><code>${SQL}</code></pre>`, SQL],
        ['br per line', `<pre><code>${SQL_LINES.join('<br>')}</code></pre>`, SQL],
        ['div per line', `<pre>${SQL_LINES.map((line) => `<div>${line}</div>`).join('')}</pre>`, SQL],
        ['code element per line', `<pre>${SQL_LINES.map((line) => `<code>${line}</code>`).join('')}</pre>`, SQL],
        [
            'div per line with highlight spans',
            `<pre><code>${SQL_LINES.map((line) => `<div><span class="token">${line}</span></div>`).join('')}</code></pre>`,
            SQL,
        ],
        ['a trailing newline of its own', '<pre><code>alpha\n</code></pre>', 'alpha\n'],
        [
            'an empty line as a div with a br',
            '<pre><div>alpha</div><div><br></div><div>beta</div></pre>',
            'alpha\n\nbeta',
        ],
    ])('pasted code block with %s keeps every line inside the block', (_name, html, code) => {
        const container = document.createElement('div')
        container.innerHTML = `<p>Hi</p>${html}`
        const doc = DOMParser.fromSchema(getSchema([...SUPPORT_EXTENSIONS])).parse(container)

        expect(serializeToMarkdown(doc.toJSON())).toBe(`Hi\n\n\`\`\`\n${code}\n\`\`\``)
    })

    it('preview schema rejects unknown node types so the plain-content fallback kicks in', () => {
        const doc: JSONContent = { type: 'doc', content: [{ type: 'table', content: [] }] }
        const schema = getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        expect(() => ProseMirrorNode.fromJSON(schema, doc)).toThrow('Unknown node type: table')
    })
})
