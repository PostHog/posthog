import { Mark, MarkViewProps, mergeAttributes } from '@tiptap/core'
import { MarkViewContent, ReactMarkViewRenderer } from '@tiptap/react'
import { useMountedLogic } from 'kea'

import { notebookLogic } from '../Notebook/notebookLogic'

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

    renderHTML({ HTMLAttributes }) {
        return [
            'span',
            mergeAttributes(HTMLAttributes, {
                class: 'NotebookComment',
            }),
            0,
        ]
    },

    addMarkView() {
        return ReactMarkViewRenderer(Component)
    },
})

const Component = (props: MarkViewProps): JSX.Element => {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)

    const attributes = mergeAttributes(props.HTMLAttributes, {
        class: 'NotebookComment',
    })

    return (
        <span {...attributes} onClick={() => mountedNotebookLogic.actions.selectComment(props.mark.attrs.id)}>
            <MarkViewContent />
        </span>
    )
}
