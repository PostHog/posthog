import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import StarterKit from '@tiptap/starter-kit'

// Shared building blocks for the markdown editors (text card, AI prompt, etc). Each editor starts
// from these and only layers on what makes it different — images, a placeholder, tables, and so on.
const MARKDOWN_BASE_EXTENSIONS = [
    StarterKit.configure({
        heading: {
            levels: [1, 2, 3],
        },
        link: false,
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
]

export const MARKDOWN_BASE_EDITABLE_EXTENSIONS = [...MARKDOWN_BASE_EXTENSIONS, Link.configure({ openOnClick: false })]

export const MARKDOWN_BASE_READONLY_EXTENSIONS = [...MARKDOWN_BASE_EXTENSIONS, Link.configure({ openOnClick: true })]
