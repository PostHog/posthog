import { JSONContent, getSchema } from '@tiptap/core'
import { DOMParser as ProseMirrorDOMParser } from '@tiptap/pm/model'

import { richContentToHtml } from './richContentToHtml'
import { SUPPORT_EXTENSIONS } from './SupportEditor'

// jest.setup.ts stubs this module out, which would make schema construction meaningless here
jest.unmock('@tiptap/extension-code-block-lowlight')

const paragraph = (...content: JSONContent[]): JSONContent => ({ type: 'paragraph', content })
const text = (value: string): JSONContent => ({ type: 'text', text: value })
const listItem = (...content: JSONContent[]): JSONContent => ({ type: 'listItem', content })

/**
 * What the composer does with a `text/html` paste: ProseMirror parses the HTML against the
 * editor's own schema. Going through it here is the point of the test, because the bug this
 * guards against is structure surviving generation but not the paste.
 */
function pasteIntoComposer(html: string): JSONContent {
    const dom = document.createElement('div')
    dom.innerHTML = html
    const parser = ProseMirrorDOMParser.fromSchema(getSchema([...SUPPORT_EXTENSIONS]))
    return parser.parse(dom).toJSON()
}

/** Node types and text only, so the comparison ignores attrs the schema fills in with defaults. */
function outline(node: JSONContent): string {
    if (node.type === 'text') {
        return node.text ?? ''
    }
    if (!node.content) {
        return `<${node.type}/>`
    }
    return `<${node.type}>${node.content.map(outline).join('')}</${node.type}>`
}

describe('richContentToHtml', () => {
    // Copying the markdown form instead flattens all of these to a run of plain paragraphs,
    // because the composer has no markdown paste parser: ProseMirror splits plain text on every
    // run of newlines, so a blank line and a line break both become one ordinary paragraph
    // boundary and list markers arrive as literal text.
    test.each<[string, JSONContent, string]>([
        [
            'paragraph breaks',
            { type: 'doc', content: [paragraph(text('one')), paragraph(text('two'))] },
            '<doc><paragraph>one</paragraph><paragraph>two</paragraph></doc>',
        ],
        [
            'a deliberate blank line between paragraphs',
            { type: 'doc', content: [paragraph(text('one')), paragraph(), paragraph(text('two'))] },
            '<doc><paragraph>one</paragraph><paragraph/><paragraph>two</paragraph></doc>',
        ],
        [
            'hard breaks within a paragraph',
            { type: 'doc', content: [paragraph(text('one'), { type: 'hardBreak' }, text('two'))] },
            '<doc><paragraph>one<hardBreak/>two</paragraph></doc>',
        ],
        [
            'list structure',
            {
                type: 'doc',
                content: [
                    {
                        type: 'bulletList',
                        content: [listItem(paragraph(text('one'))), listItem(paragraph(text('two')))],
                    },
                ],
            },
            '<doc><bulletList><listItem><paragraph>one</paragraph></listItem>' +
                '<listItem><paragraph>two</paragraph></listItem></bulletList></doc>',
        ],
    ])('survives a paste into the composer: %s', (_name, content, expected) => {
        const html = richContentToHtml(content)
        expect(html).not.toBeNull()
        expect(outline(pasteIntoComposer(html as string))).toEqual(expected)
    })

    it('returns null for content the schema cannot render, so the copy falls back to plain text', () => {
        expect(richContentToHtml({ type: 'doc', content: [{ type: 'somethingUnknown' }] })).toBeNull()
    })
})
