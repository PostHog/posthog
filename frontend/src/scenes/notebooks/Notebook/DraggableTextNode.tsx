import Heading from '@tiptap/extension-heading'
import Paragraph from '@tiptap/extension-paragraph'
import { NodeViewContent, NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import './DraggableTextNode.scss'

function DraggableParagraphView({ editor }: NodeViewProps): JSX.Element {
    const isEditable = editor.isEditable

    return (
        <NodeViewWrapper className="DraggableTextNode">
            {isEditable && (
                <div className="DraggableTextNode__handle" contentEditable={false} data-drag-handle>
                    <IconDragHandle className="DraggableTextNode__handle-icon" />
                </div>
            )}
            <NodeViewContent as="p" className="DraggableTextNode__content" />
        </NodeViewWrapper>
    )
}

function DraggableHeadingView({ editor, node }: NodeViewProps): JSX.Element {
    const isEditable = editor.isEditable
    const level = node.attrs.level as 1 | 2 | 3 | 4 | 5 | 6
    const Tag = `h${level}` as const

    return (
        <NodeViewWrapper className="DraggableTextNode DraggableTextNode--heading">
            {isEditable && (
                <div className="DraggableTextNode__handle" contentEditable={false} data-drag-handle>
                    <IconDragHandle className="DraggableTextNode__handle-icon" />
                </div>
            )}
            <NodeViewContent as={Tag} className="DraggableTextNode__content" />
        </NodeViewWrapper>
    )
}

export const DraggableParagraph = Paragraph.extend({
    draggable: true,

    addNodeView() {
        return ReactNodeViewRenderer(DraggableParagraphView)
    },
})

export const DraggableHeading = Heading.extend({
    draggable: true,

    addNodeView() {
        return ReactNodeViewRenderer(DraggableHeadingView)
    },
})
