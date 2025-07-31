import { Mark, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'
import { BuiltLogic } from 'kea'

import type { notebookLogicType } from '../Notebook/notebookLogicType'
import { Attributes } from '@tiptap/core'
import { DOMOutputSpec, TagParseRule } from '@tiptap/pm/model'

export const NotebookMarkComment = Mark.create({
    name: 'comment',
    spanning: false,

    addAttributes(): Attributes {
        return {
            id: {
                default: null,
                parseHTML: (el) => (el as HTMLSpanElement).dataset.id,
                renderHTML: (attrs) => ({ 'data-id': attrs.id }),
            },
        }
    },

    parseHTML(): TagParseRule[] {
        return [
            {
                tag: 'span[data-id]',
                getAttrs: (el) => !!(el as HTMLSpanElement).dataset.id?.trim() && null,
            },
        ]
    },

    onSelectionUpdate(): void {
        if (this.editor.isActive('comment')) {
            const notebookLogic = this.editor.extensionStorage._notebookLogic as BuiltLogic<notebookLogicType>
            notebookLogic.actions.selectComment(this.editor.getAttributes('comment').id)
        }
    },

    renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, any> }): DOMOutputSpec {
        return [
            'span',
            mergeAttributes(HTMLAttributes, {
                class: clsx('NotebookComment'),
            }),
            0,
        ]
    },
})
