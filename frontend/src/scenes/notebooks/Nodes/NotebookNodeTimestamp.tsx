import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'
import { useValues } from 'kea'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { dayjs } from 'lib/dayjs'

const Component = (props: NodeViewProps): JSX.Element => {
    const playbackTime = props.node.attrs.playbackTime
    const sessionRecordingId = props.node.attrs.sessionRecordingId

    const recordingLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey: `notebook-${sessionRecordingId}`,
    }

    const { currentPlayerTime } = useValues(sessionRecordingPlayerLogic(recordingLogicProps))

    return <NodeViewWrapper as="span">{formatTimestamp(playbackTime || currentPlayerTime)}</NodeViewWrapper>
}

function formatTimestamp(time: number): string {
    return dayjs.duration(time, 'milliseconds').format('HH:mm:ss').replace(/^00:/, '').trim()
}

export const NotebookNodeTimestamp = Node.create({
    name: NotebookNodeType.Timestamp,
    inline: true,
    group: 'inline',
    atom: true,

    addAttributes() {
        return {
            playbackTime: { default: null, keepOnSplit: false },
            sessionRecordingId: { default: null, keepOnSplit: true, isRequired: true },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Timestamp,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Timestamp, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
