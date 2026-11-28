import { Editor, JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'

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

    it('preview schema rejects unknown node types so the plain-content fallback kicks in', () => {
        const doc: JSONContent = { type: 'doc', content: [{ type: 'table', content: [] }] }
        const schema = getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        expect(() => ProseMirrorNode.fromJSON(schema, doc)).toThrow('Unknown node type: table')
    })
})

const shiftEnterLines = (...lines: string[]): JSONContent => ({
    type: 'paragraph',
    content: lines.flatMap((line, index) => [
        ...(index > 0 ? [{ type: 'hardBreak' }] : []),
        ...(line ? [{ type: 'text', text: line }] : []),
    ]),
})

describe('SupportEditor code block toggle', () => {
    let editor: Editor

    const setUp = (...blocks: JSONContent[]): void => {
        editor = new Editor({
            element: document.createElement('div'),
            extensions: SUPPORT_EXTENSIONS,
            content: { type: 'doc', content: blocks },
        })
    }

    const blocks = (): string[] => {
        const result: string[] = []
        editor.state.doc.forEach((node) => {
            result.push(`${node.type.name}: ${node.textBetween(0, node.content.size, '\n', '\n')}`)
        })
        return result
    }

    const rangeOf = (text: string): { from: number; to: number } => {
        let range: { from: number; to: number } | null = null
        editor.state.doc.descendants((node, pos) => {
            if (node.isText && node.text === text) {
                range = { from: pos, to: pos + text.length }
            }
        })
        if (!range) {
            throw new Error(`"${text}" is not in the document`)
        }
        return range
    }

    const selectedText = (): string =>
        editor.state.doc.textBetween(editor.state.selection.from, editor.state.selection.to)

    afterEach(() => {
        editor.destroy()
    })

    it('gives an empty code block for the empty line with the cursor, not the lines above it', () => {
        setUp(shiftEnterLines('one', 'two', ''))
        editor.commands.setTextSelection(editor.state.doc.content.size - 1)

        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one\ntwo', 'codeBlock: ', 'paragraph: '])
        expect(editor.state.selection.$from.parent.type.name).toBe('codeBlock')
    })

    it('wraps only the line with the cursor and keeps the cursor in place', () => {
        setUp(shiftEnterLines('one', 'two', 'three'))
        editor.commands.setTextSelection(rangeOf('two').from + 1)

        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one', 'codeBlock: two', 'paragraph: three'])
        expect(editor.state.selection.$from.parent.type.name).toBe('codeBlock')
        expect(editor.state.selection.$from.parentOffset).toBe(1)
    })

    it('wraps only the selected line and keeps it selected', () => {
        setUp(shiftEnterLines('one', 'two', 'three'))
        editor.commands.setTextSelection(rangeOf('two'))

        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one', 'codeBlock: two', 'paragraph: three'])
        expect(selectedText()).toBe('two')
    })

    it('wraps a selection over several lines in one code block', () => {
        setUp(shiftEnterLines('one', 'two', 'three', 'four'))
        editor.commands.setTextSelection({ from: rangeOf('two').from, to: rangeOf('three').to })

        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one', 'codeBlock: two\nthree', 'paragraph: four'])
    })

    it('wraps only the line with the cursor from the Mod-Alt-c shortcut', () => {
        setUp(shiftEnterLines('one', 'two', 'three'))
        editor.commands.setTextSelection(rangeOf('two').from)

        editor.view.dom.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'c', ctrlKey: true, altKey: true, bubbles: true })
        )

        expect(blocks()).toEqual(['paragraph: one', 'codeBlock: two', 'paragraph: three'])
    })

    it('wraps only the current paragraph when the lines are typed with Enter', () => {
        setUp(paragraph('one'), paragraph('two'), { type: 'paragraph' })
        editor.commands.setTextSelection(editor.state.doc.content.size - 1)

        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one', 'paragraph: two', 'codeBlock: ', 'paragraph: '])
    })

    it('turns the code block back into a paragraph on a second toggle', () => {
        setUp(shiftEnterLines('one', 'two', 'three'))
        editor.commands.setTextSelection(rangeOf('two'))

        editor.commands.toggleCodeBlock()
        editor.commands.toggleCodeBlock()

        expect(blocks()).toEqual(['paragraph: one', 'paragraph: two', 'paragraph: three'])
    })
})
