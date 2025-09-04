import { Node } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { useValues } from 'kea'

import { RichContentNodeType } from '../types'
import { richContentEditorSectionNodeLogic } from './richContentEditorSectionNodeLogic'

const Component = (): JSX.Element => {
    useValues(richContentEditorSectionNodeLogic)
    // const { open } = useValues(richContentEditorSectionNodeLogic)

    return <NodeViewWrapper className="react-component">{'Closed content'}</NodeViewWrapper>
}

export default Node.create({
    name: RichContentNodeType.SectionContent,
    content: 'block+',
    defining: true,
    selectable: false,

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
