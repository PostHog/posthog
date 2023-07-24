import { NotebookNodeType } from '~/types'
import { hasDirectChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Node } from '@tiptap/pm/model'
import { useValues } from 'kea'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { notebookLogic } from '../Notebook/notebookLogic'

const Component = ({ previousNode }: InsertionSuggestionViewProps): JSX.Element => {
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic(sessionRecordingPlayerProps(previousNode?.attrs.sessionRecordingId))
    )

    return (
        <div className="NotebookRecordingTimestamp NotebookRecordingTimestamp--preview">
            {formatTimestamp(currentPlayerTime)}
        </div>
    )
}

export default InsertionSuggestion.create({
    shouldShow: ({ previousNode }) =>
        !!previousNode ? hasDirectChildOfType(previousNode, NotebookNodeType.ReplayTimestamp) : false,

    onTab: ({ previousNode }: { previousNode: Node | null }) => {
        const { editor } = useValues(notebookLogic)

        if (!!previousNode && !!editor) {
            const sessionRecordingId = previousNode.attrs.sessionRecordingId

            const currentPlayerTime =
                sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                    .currentPlayerTime || 0

            editor.insertContent(buildTimestampCommentContent(currentPlayerTime, sessionRecordingId))
        }
    },

    Component,
})
