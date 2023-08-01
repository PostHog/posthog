import { NotebookNodeType } from '~/types'
import { firstChildOfType, hasChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useValues } from 'kea'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { Node, NotebookEditor } from '../Notebook/utils'

const Component = ({ previousNode }: InsertionSuggestionViewProps): JSX.Element => {
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic(sessionRecordingPlayerProps(getSessionRecordingId(previousNode)))
    )

    return (
        <div className="NotebookRecordingTimestamp NotebookRecordingTimestamp--preview">
            {formatTimestamp(currentPlayerTime)}
        </div>
    )
}

export default InsertionSuggestion.create({
    shouldShow: ({ previousNode }) => {
        return !!previousNode
            ? previousNode.type.name === NotebookNodeType.Recording ||
                  hasChildOfType(previousNode, NotebookNodeType.ReplayTimestamp)
            : false
    },

    onTab: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: Node | null }) => {
        if (!!previousNode && !!editor) {
            const sessionRecordingId = getSessionRecordingId(previousNode)

            const currentPlayerTime =
                sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                    .currentPlayerTime || 0

            editor.insertContent([buildTimestampCommentContent(currentPlayerTime, sessionRecordingId)])
        }
    },

    Component,
})

function getSessionRecordingId(node: Node | null): string {
    return node?.type.name === NotebookNodeType.Recording
        ? node.attrs.id
        : getTimestampChildNode(node).attrs.sessionRecordingId
}

function getTimestampChildNode(node: Node | null): Node {
    return firstChildOfType(node as Node, NotebookNodeType.ReplayTimestamp) as Node
}
