import { Editor } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import StarterKit from '@tiptap/starter-kit'

import { NotebookTrailingParagraph } from './NotebookTrailingParagraph'

const CustomDocument = ExtensionDocument.extend({
    content: 'heading block*',
})

describe('NotebookTrailingParagraph', () => {
    function createTestEditor(content: Record<string, unknown>): Editor {
        const element = document.createElement('div')
        document.body.appendChild(element)

        return new Editor({
            element,
            extensions: [
                CustomDocument,
                StarterKit.configure({
                    document: false,
                    gapcursor: false,
                    trailingNode: false,
                }),
                NotebookTrailingParagraph,
            ],
            content,
        })
    }

    function clickBelowLastLine(editor: Editor): void {
        const lastChild = editor.view.dom.lastElementChild
        expect(lastChild).not.toBeNull()

        jest.spyOn(lastChild as Element, 'getBoundingClientRect').mockReturnValue({
            bottom: 100,
        } as DOMRect)
        Object.defineProperty(document, 'elementFromPoint', {
            configurable: true,
            value: jest.fn(() => lastChild),
        })

        editor.view.dom.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientY: 120 }))
    }

    afterEach(() => {
        document.body.innerHTML = ''
        delete (document as { elementFromPoint?: unknown }).elementFromPoint
        jest.restoreAllMocks()
    })

    it('inserts a paragraph after the required heading when clicking below the last line', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'heading', attrs: { level: 1 } }],
        })

        clickBelowLastLine(editor)

        const doc = editor.getJSON()
        expect(doc.content).toHaveLength(2)
        expect(doc.content![0].type).toBe('heading')
        expect(doc.content![1].type).toBe('paragraph')
        editor.destroy()
    })

    it('focuses an existing empty trailing paragraph instead of adding another one', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'heading', attrs: { level: 1 } }, { type: 'paragraph' }],
        })

        clickBelowLastLine(editor)

        const doc = editor.getJSON()
        expect(doc.content).toHaveLength(2)
        expect(doc.content![1].type).toBe('paragraph')
        editor.destroy()
    })

    it('does nothing when the editor is read-only', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'heading', attrs: { level: 1 } }],
        })
        editor.setEditable(false)

        clickBelowLastLine(editor)

        const doc = editor.getJSON()
        expect(doc.content).toHaveLength(1)
        expect(doc.content![0].type).toBe('heading')
        editor.destroy()
    })
})
