import { Editor } from '@tiptap/core'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import StarterKit from '@tiptap/starter-kit'

import { NotebookDefaultBlockOnEnter } from './NotebookDefaultBlockOnEnter'

describe('NotebookDefaultBlockOnEnter', () => {
    function createTestEditor(content: Record<string, unknown>): Editor {
        return new Editor({
            extensions: [
                StarterKit,
                TaskList,
                TaskItem.configure({ nested: true }),
                NotebookDefaultBlockOnEnter,
            ],
            content,
        })
    }

    function pressEnter(editor: Editor): void {
        editor.commands.keyboardShortcut('Enter')
    }

    it('creates a new bullet list item when pressing Enter inside a bullet list', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [
                {
                    type: 'bulletList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'item one' }] }],
                        },
                    ],
                },
            ],
        })

        // Place cursor at the end of "item one"
        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        const bulletList = doc.content![0]
        expect(bulletList.type).toBe('bulletList')
        // Should now have 2 list items
        expect(bulletList.content).toHaveLength(2)
        expect(bulletList.content![0].type).toBe('listItem')
        expect(bulletList.content![1].type).toBe('listItem')
    })

    it('creates a new ordered list item when pressing Enter inside an ordered list', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [
                {
                    type: 'orderedList',
                    content: [
                        {
                            type: 'listItem',
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'first' }] }],
                        },
                    ],
                },
            ],
        })

        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        const orderedList = doc.content![0]
        expect(orderedList.type).toBe('orderedList')
        expect(orderedList.content).toHaveLength(2)
        expect(orderedList.content![0].type).toBe('listItem')
        expect(orderedList.content![1].type).toBe('listItem')
    })

    it('creates a new task item when pressing Enter inside a task list', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [
                {
                    type: 'taskList',
                    content: [
                        {
                            type: 'taskItem',
                            attrs: { checked: false },
                            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'todo' }] }],
                        },
                    ],
                },
            ],
        })

        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        const taskList = doc.content![0]
        expect(taskList.type).toBe('taskList')
        expect(taskList.content).toHaveLength(2)
        expect(taskList.content![0].type).toBe('taskItem')
        expect(taskList.content![1].type).toBe('taskItem')
    })

    it('creates a plain paragraph when pressing Enter in a regular paragraph', () => {
        const editor = createTestEditor({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hello world' }] }],
        })

        // Place cursor at the end of "hello world"
        editor.commands.focus('end')

        pressEnter(editor)

        const doc = editor.getJSON()
        // Should have 2 paragraphs now
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
        // StarterKit's trailingNode may add an extra paragraph — just check the first two nodes
        expect(doc.content!.length).toBeGreaterThanOrEqual(2)
        expect(doc.content![0].type).toBe('heading')
        // The new block after the heading should be a paragraph, not another heading
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

        // Place cursor after "abc": doc > bulletList > listItem > paragraph > "abcdef"
        // Find the correct offset by resolving from the paragraph start
        const $start = editor.state.doc.resolve(4) // position 4 is start of text inside paragraph
        const splitPos = $start.start() + 3 // 3 chars into "abcdef"
        editor.commands.setTextSelection(splitPos)

        pressEnter(editor)

        const doc = editor.getJSON()
        const bulletList = doc.content![0]
        expect(bulletList.type).toBe('bulletList')
        expect(bulletList.content).toHaveLength(2)

        // First item should have "abc"
        const firstItemText = bulletList.content![0].content![0].content![0].text
        expect(firstItemText).toBe('abc')

        // Second item should have "def"
        const secondItemText = bulletList.content![1].content![0].content![0].text
        expect(secondItemText).toBe('def')
    })
})
