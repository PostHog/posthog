import { Editor as TTEditor } from '@tiptap/core'
import { NotebookNodeType } from '~/types'
import { hasDirectChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Node } from '@tiptap/pm/model'
import { useValues } from 'kea'

function shouldShow({ editor }: { editor: TTEditor }): boolean {
    const { $anchor } = editor.state.selection
    const node = $anchor.node(1)
    const previousNode = editor.state.doc.childBefore($anchor.pos - node.nodeSize).node

    return !!previousNode ? hasDirectChildOfType(previousNode, NotebookNodeType.ReplayTimestamp) : false
}

const Component = ({ previousNode }: { previousNode: Node | null }): React.ReactNode => {
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic(sessionRecordingPlayerProps(previousNode?.attrs.sessionRecordingId))
    )

    return (
        <div className="NotebookRecordingTimestamp NotebookRecordingTimestamp--preview">
            {formatTimestamp(currentPlayerTime)}
        </div>
    )
}

function onTab({ editor, previousNode }: { editor: TTEditor; previousNode: Node | null }): void {
    if (previousNode) {
        const sessionRecordingId = previousNode.attrs.sessionRecordingId

        const currentPlayerTime =
            sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                .currentPlayerTime || 0

        editor.chain().insertContent(buildTimestampCommentContent(currentPlayerTime, sessionRecordingId)).focus().run()
    }
}

export default {
    shouldShow,
    Component,
    onTab,
}
