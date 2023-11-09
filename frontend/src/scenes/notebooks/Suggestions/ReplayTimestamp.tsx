import { NotebookEditor, NotebookNodeType } from '~/types'
import { firstChildOfType, hasChildOfType } from '../Notebook/Editor'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useValues } from 'kea'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { TipTapNode } from '../Notebook/types'
import { LemonButton } from '@posthog/lemon-ui'

const insertTimestamp = ({
    editor,
    previousNode,
}: {
    editor: NotebookEditor | null
    previousNode: TipTapNode | null
}): void => {
    if (!!previousNode && !!editor) {
        const sessionRecordingId = getSessionRecordingId(previousNode)

        const currentPlayerTime =
            sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                .currentPlayerTime || 0

        editor.insertContent([buildTimestampCommentContent({ playbackTime: currentPlayerTime, sessionRecordingId })])
    }
}

const Component = ({ previousNode, editor }: InsertionSuggestionViewProps): JSX.Element => {
    const { currentPlayerTime } = useValues(
        sessionRecordingPlayerLogic(sessionRecordingPlayerProps(getSessionRecordingId(previousNode)))
    )

    return (
        <div className="NotebookRecordingTimestamp opacity-50">
            <LemonButton
                size="small"
                noPadding
                type="secondary"
                status="primary-alt"
                onClick={() => insertTimestamp({ previousNode, editor })}
            >
                <span className="p-1">{formatTimestamp(currentPlayerTime)}</span>
            </LemonButton>
        </div>
    )
}

export default InsertionSuggestion.create({
    shouldShow: ({ previousNode }) => {
        return previousNode
            ? previousNode.type.name === NotebookNodeType.Recording ||
                  hasChildOfType(previousNode, NotebookNodeType.ReplayTimestamp)
            : false
    },

    onTab: insertTimestamp,

    Component,
})

function getSessionRecordingId(node: TipTapNode | null): string {
    return node?.type.name === NotebookNodeType.Recording
        ? node.attrs.id
        : getTimestampChildNode(node).attrs.sessionRecordingId
}

function getTimestampChildNode(node: TipTapNode | null): TipTapNode {
    return firstChildOfType(node as TipTapNode, NotebookNodeType.ReplayTimestamp) as TipTapNode
}
