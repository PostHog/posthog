import { Editor } from '@tiptap/core'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import StarterKit from '@tiptap/starter-kit'

import { NotebookDefaultBlockOnEnter } from './NotebookDefaultBlockOnEnter'

describe('NotebookDefaultBlockOnEnter', () => {
    function createTestEditor(content: Record<string, unknown>): Editor {
        return new Editor({
            extensions: [StarterKit, TaskList, TaskItem.configure({ nested: true }), NotebookDefaultBlockOnEnter],
            content,
        })
    }

    function pressEnter(editor: Editor): void {
        editor.commands.keyboardShortcut('Enter')
    }

    it.each([
        {
            label: 'bullet list',
            listType: 'bulletList',
            itemType: 'listItem',
            item: {
                type: 'listItem',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'item' }] }],
            },
        },
        {
            label: 'ordered list',
            listType: 'orderedList',
            itemType: 'listItem',
            item: {
                type: 'listItem',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'item' }] }],
            },
        },
        {
            label: 'task list',
            listType: 'taskList',
            itemType: 'taskItem',
            item: {
                type: 'taskItem',
                attrs: { checked: false },
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'item' }] }],
            },
        },
    ])('creates a new $label item when pressing Enter inside a $label', ({ listType, itemType, item }) => {
        const editor = createTestEditor({ type: 'doc', content: [{ type: listType, content: [item] }] })
        editor.commands.focus('end')
        pressEnter(editor)
        const list = editor.getJSON().content![0]
        expect(list.type).toBe(listType)
        expect(list.content).toHaveLength(2)
        expect(list.content![1].type).toBe(itemType)
    })

    it('creates a plain paragraph when pressing Enter in a regular paragraph', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hello world' }] }],
        })

        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        expect(doc.content).toHaveLength(2)
        expect(doc.content![0].type).toBe('paragraph')
        expect(doc.content![1].type).toBe('paragraph')
    })

    it('converts heading to paragraph when pressing Enter at end of heading', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Title' }] }],
        })

        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        expect(doc.content!.length).toBeGreaterThanOrEqual(2)
        expect(doc.content![0].type).toBe('heading')
        expect(doc.content![1].type).toBe('paragraph')
    })

    it('splits bullet list item text at cursor position', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'abcdef' }] }],
                        },
                    ],
                },
            ],
        })

        let splitPos = 0
        editor.state.doc.descendants((node, pos) => {
            if (node.isText && node.text === 'abcdef') {
                splitPos = pos + 3
            }
        })
        editor.commands.setTextSelection(splitPos)

        pressEnter(editor)

        const doc = editor.getJSON()
        const bulletList = doc.content![0]
        expect(bulletList.type).toBe('bulletList')
        expect(bulletList.content).toHaveLength(2)

        const firstItem = bulletList.content![0] as any
        expect(firstItem.content[0].content[0].text).toBe('abc')

        const secondItem = bulletList.content![1] as any
        expect(secondItem.content[0].content[0].text).toBe('def')
    })
})
