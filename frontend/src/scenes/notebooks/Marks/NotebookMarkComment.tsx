import { Mark, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'

export const NotebookMarkComment = Mark.create({
    name: 'comment',
    priority: 1001,
    keepOnSplit: false,
    inclusive: true,

    addAttributes() {
        return {
            id: {
                default: null,
                parseHTML: (el) => (el as HTMLSpanElement).dataset.id,
                renderHTML: (attrs) => ({ 'data-id': attrs.id }),
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: 'span[data-id]',
                getAttrs: (el) => !!(el as HTMLSpanElement).dataset.id?.trim() && null,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [
            'span',
            mergeAttributes(HTMLAttributes, {
                class: clsx('NotebookComment'),
            }),
            0,
        ]
    },
})
