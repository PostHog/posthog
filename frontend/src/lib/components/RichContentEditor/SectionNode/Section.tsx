import { Node, NodeViewProps } from '@tiptap/core'
import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { uuid } from 'lib/utils'

import { RichContentNodeType } from '../types'
import { richContentEditorSectionNodeLogic } from './richContentEditorSectionNodeLogic'

const Component = (props: NodeViewProps): JSX.Element => {
    const id = '123456765432'

    console.log(id, props.node.attrs.open)

    return (
        <NodeViewWrapper className="react-component">
            <BindLogic logic={richContentEditorSectionNodeLogic} props={{ id: '123456765432', open: true }}>
                <NodeViewContent className="content" />
            </BindLogic>
        </NodeViewWrapper>
    )
}

export default Node.create({
    name: RichContentNodeType.Section,
    content: [RichContentNodeType.SectionSummary, RichContentNodeType.SectionContent].join(' '),
    group: 'block',
    defining: true,
    isolating: true,

    addAttributes() {
        return {
            open: { default: false },
        }
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
