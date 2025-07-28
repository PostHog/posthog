import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { NotebookNodeType } from '~/types'

import { sessionRecordingPlayerProps } from '../Nodes/NotebookNodeRecording'
import { buildTimestampCommentContent, formatTimestamp } from '../Nodes/NotebookNodeReplayTimestamp'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { RichContentEditorType, RichContentNode } from 'lib/components/RichContentEditor/types'
import { firstChildOfType, hasChildOfType } from 'lib/components/RichContentEditor/utils'

const insertTimestamp = ({
    editor,
    previousNode,
}: {
    editor: RichContentEditorType | null
    previousNode: RichContentNode | null
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
            <LemonButton size="small" noPadding active onClick={() => insertTimestamp({ previousNode, editor })}>
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

function getSessionRecordingId(node: RichContentNode | null): string {
    return node?.type.name === NotebookNodeType.Recording
        ? node.attrs.id
        : getTimestampChildNode(node).attrs.sessionRecordingId
}

function getTimestampChildNode(node: RichContentNode | null): RichContentNode {
    return firstChildOfType(node as RichContentNode, NotebookNodeType.ReplayTimestamp) as RichContentNode
}
