import { Editor as TTEditor } from '@tiptap/core'
import { NotebookNodeType } from '~/types'
import { hasDirectChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

function shouldShow({ editor }: { editor: TTEditor }): boolean {
    const { $anchor } = editor.state.selection
    const node = $anchor.node(1)
    const previousNode = editor.state.doc.childBefore($anchor.pos - node.nodeSize).node

    return !!previousNode ? hasDirectChildOfType(previousNode, NotebookNodeType.ReplayTimestamp) : false
}

const Component = (): React.ReactNode => {
    return <div>Hello</div>
}

function onTab({ editor }: { editor: TTEditor }): void {
    console.log('Tab pressed')
    const { $anchor } = editor.state.selection
    const node = $anchor.node(1)
    const previousNode = editor.state.doc.childBefore($anchor.pos - node.nodeSize).node

    if (previousNode) {
        const sessionRecordingId = previousNode.attrs.sessionRecordingId

        const currentPlayerTime =
            sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                .currentPlayerTime || 0

        editor.commands.insertContent(buildTimestampCommentContent(currentPlayerTime, sessionRecordingId))
    }
}

export default {
    shouldShow,
    Component,
    onTab,
}
