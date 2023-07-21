import { Editor as TTEditor } from '@tiptap/core'
import { NotebookNodeType } from '~/types'
import { hasDirectChildOfType } from '../Notebook/Editor'

function shouldShow({ editor }: { editor: TTEditor }): boolean {
    const { $anchor } = editor.state.selection
    const node = $anchor.node(1)
    const previousNode = editor.state.doc.childBefore($anchor.pos - node.nodeSize).node

    return !!previousNode ? hasDirectChildOfType(previousNode, NotebookNodeType.ReplayTimestamp) : false
}

const Component = (): React.ReactNode => {
    return <div>Hello</div>
}

export default {
    shouldShow,
    Component,
}
