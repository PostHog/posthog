import { NotebookNodeType } from '~/types'
import { firstChildOfType, hasChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useValues } from 'kea'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { Node, NotebookEditor } from '../Notebook/utils'

const Component = ({ previousNode }: InsertionSuggestionViewProps): JSX.Element => {
    const timestampNode = getTimestampChildNode(previousNode)
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic(sessionRecordingPlayerProps(timestampNode.attrs.sessionRecordingId))
    )

    return (
        <div className="NotebookRecordingTimestamp NotebookRecordingTimestamp--preview">
            {formatTimestamp(currentPlayerTime)}
        </div>
    )
}

export default InsertionSuggestion.create({
    shouldShow: ({ previousNode }) =>
        !!previousNode ? hasChildOfType(previousNode, NotebookNodeType.ReplayTimestamp) : false,

    onTab: ({ editor, previousNode }: { editor: NotebookEditor | null; previousNode: Node | null }) => {
        if (!!previousNode && !!editor) {
            const timestampNode = getTimestampChildNode(previousNode)
            const sessionRecordingId = timestampNode.attrs.sessionRecordingId

            const currentPlayerTime =
                sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                    .currentPlayerTime || 0

            editor.insertContent(buildTimestampCommentContent(currentPlayerTime, sessionRecordingId))
        }
    },

    Component,
})

function getTimestampChildNode(node: Node | null): Node {
    return firstChildOfType(node as Node, NotebookNodeType.ReplayTimestamp) as Node
}
