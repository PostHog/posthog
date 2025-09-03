import { Node } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'

import { RichContentNodeType } from '../types'

const Component = (): JSX.Element => {
    return <NodeViewWrapper className="react-component">React Component</NodeViewWrapper>
}

export default Node.create({
    name: RichContentNodeType.Section,

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
