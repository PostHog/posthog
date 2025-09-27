import { Node } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'

import { RichContentNodeType } from '../types'

const Component = (): JSX.Element => {
    return <NodeViewWrapper className="react-component">Title</NodeViewWrapper>
}

export default Node.create({
    name: RichContentNodeType.SectionSummary,
    content: 'text*',
    defining: true,
    selectable: false,
    isolating: true,

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
