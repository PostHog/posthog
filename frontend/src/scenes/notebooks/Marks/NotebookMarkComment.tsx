import { Mark, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'
import { BuiltLogic } from 'kea'

import type { notebookLogicType } from '../Notebook/notebookLogicType'

export const NotebookMarkComment = Mark.create({
    name: 'comment',
    spanning: false,

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

    onSelectionUpdate() {
        if (this.editor.isActive('comment')) {
            const notebookLogic = this.editor.extensionStorage._notebookLogic as BuiltLogic<notebookLogicType>
            notebookLogic.actions.selectComment(this.editor.getAttributes('comment').id)
        }
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
