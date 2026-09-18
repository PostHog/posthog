import { JSONContent, getSchema } from '@tiptap/core'
import { DOMParser as ProseMirrorDOMParser } from '@tiptap/pm/model'

import { RichContentNodeType } from 'lib/components/RichContentEditor/types'

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

    it('keeps a mention readable outside PostHog and a node inside it', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [paragraph(text('ask '), { type: RichContentNodeType.Mention, attrs: { id: 5 } })],
        }
        const html = richContentToHtml(content) as string

        // A mail client renders the text and ignores the tag it does not know
        expect(html).toContain('@member:5')
        // The composer restores the node from the tag, and its node view renders the name again
        expect(outline(pasteIntoComposer(html))).toEqual(
            `<doc><paragraph>ask <${RichContentNodeType.Mention}/></paragraph></doc>`
        )
    })

    // Both of these render as the plain-text form for the reader, so the clipboard has to agree.
    // `generateHTML` builds the document without checking it, so an invalid structure of known
    // node types would otherwise serialize to HTML the message never displayed.
    test.each<[string, JSONContent]>([
        ['an unknown node type', { type: 'doc', content: [{ type: 'somethingUnknown' }] }],
        ['known node types in an invalid structure', { type: 'doc', content: [text('bare text under doc')] }],
    ])('returns null for %s, so the copy falls back to plain text', (_name, content) => {
        expect(richContentToHtml(content)).toBeNull()
    })
})
