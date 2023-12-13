import { Mark, mergeAttributes } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import clsx from 'clsx'

import { notebookCommentLogic } from '../Notebook/notebookCommentLogic'

export const NotebookMarkComment = Mark.create({
    name: 'comment',
    priority: 1001,
    keepOnSplit: false,
    inclusive: true,

    addAttributes() {
        return {
            id: { default: null },
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

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('handleLinkClick'),
                props: {
                    handleDOMEvents: {
                        click(_, event) {
                            const comment = event.target as HTMLAnchorElement
                            const logic = notebookCommentLogic.findMounted()
                            logic?.actions.setCommentId(comment.id)
                        },
                    },
                },
            }),
        ]
    },
})
