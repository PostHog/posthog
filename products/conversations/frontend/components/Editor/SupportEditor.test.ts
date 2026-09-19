import { Editor, JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'

import {
    SUPPORT_EXTENSIONS,
    SUPPORT_PREVIEW_EXTENSIONS,
    SubmitOnEnterExtension,
    serializeToMarkdown,
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

describe('SupportEditor Enter-to-send binding', () => {
    function buildEditor(enabled: boolean, onSubmit: () => void, content: JSONContent): Editor {
        return new Editor({
            element: document.createElement('div'),
            extensions: [
                ...SUPPORT_EXTENSIONS,
                SubmitOnEnterExtension.configure({ isEnabled: () => enabled, onSubmit }),
            ],
            content,
        })
    }

    function pressEnter(editor: Editor, shiftKey = false): void {
        editor.commands.setTextSelection(editor.state.doc.content.size - 1)
        editor.view.someProp('handleKeyDown', (handler) =>
            handler(editor.view, new KeyboardEvent('keydown', { key: 'Enter', shiftKey }))
        )
    }

    const codeBlock: JSONContent = {
        type: 'doc',
        content: [{ type: 'codeBlock', content: [{ type: 'text', text: 'print(1)' }] }],
    }
    const list: JSONContent = {
        type: 'doc',
        content: [{ type: 'bulletList', content: [listItem(paragraph('one'))] }],
    }
    const reply: JSONContent = { type: 'doc', content: [paragraph('Thanks, that is fixed now')] }

    // Enter only sends where it has no other job. Everywhere else it stays an editing key,
    // so the agent never loses a keystroke to an unintended send or to a swallowed Enter.
    it.each<[string, boolean, JSONContent, boolean, boolean]>([
        ['sends a reply when the preference is on', true, reply, false, true],
        ['leaves a reply alone when the preference is off', false, reply, false, false],
        ['leaves a reply alone when Shift is held', true, reply, true, false],
        ['does not send an empty composer', true, { type: 'doc', content: [paragraph('')] }, false, false],
        ['does not send from a list item', true, list, false, false],
        ['does not send from a code block', true, codeBlock, false, false],
    ])('%s', (_name, enabled, content, shiftKey, expectedToSend) => {
        const onSubmit = jest.fn()
        const editor = buildEditor(enabled, onSubmit, content)
        const docBefore = editor.state.doc.toJSON()

        pressEnter(editor, shiftKey)

        expect(onSubmit).toHaveBeenCalledTimes(expectedToSend ? 1 : 0)
        // A send leaves the draft in place for the composer to clear; anything else must
        // have done its usual edit rather than nothing at all.
        if (expectedToSend) {
            expect(editor.state.doc.toJSON()).toEqual(docBefore)
        } else {
            expect(editor.state.doc.toJSON()).not.toEqual(docBefore)
        }
        editor.destroy()
    })
})
