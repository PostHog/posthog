import { Mark, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'

export const NotebookMarkComment = Mark.create({
    name: 'comment',
    priority: 1001,
    keepOnSplit: false,
    inclusive: true,

    addAttributes() {
        return {
            commentId: {
                default: null,
                parseHTML: (el) => (el as HTMLSpanElement).dataset.commentId,
                renderHTML: (attrs) => ({ 'data-comment-id': attrs.commentId }),
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: 'span[data-comment-id]',
                getAttrs: (el) => !!(el as HTMLSpanElement).dataset.commentId?.trim() && null,
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
