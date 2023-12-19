import { Mark, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

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
                tag: 'span[data-id]',
                getAttrs: (el) => !!(el as HTMLSpanElement).dataset.id?.trim() && null,
            },
            {
                tag: 'span[data-comment-id]',
                getAttrs: (el) => !!(el as HTMLSpanElement).dataset.commentId?.trim() && null,
            },
        ]
    },

    onSelectionUpdate() {
        if (this.editor.isActive('comment')) {
            const logic = sidePanelStateLogic.findMounted()
            logic?.actions.openSidePanel(SidePanelTab.Discussion)
            const attrs = this.editor.getAttributes('comment')
            const el = document.querySelector(`.Comment[data-comment-id='${attrs.commentId}']`)
            el?.scrollIntoView()
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
