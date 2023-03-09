import { mergeAttributes, Node } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'

const COMPONENT_CLASS_NAME = 'ph-recording'

interface ComponentProps {
    sessionRecordingId: string
}

const Component = ({ sessionRecordingId }: ComponentProps): JSX.Element => {
    return (
        <NodeWrapper className={COMPONENT_CLASS_NAME}>
            <SessionRecordingPlayer
                sessionRecordingId={sessionRecordingId}
                playerKey={`notebook-${sessionRecordingId}`}
            />
        </NodeWrapper>
    )
}

export const RecordingNode = Node.create({
    name: 'posthogRecording',
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            count: {
                default: 0,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: COMPONENT_CLASS_NAME,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [COMPONENT_CLASS_NAME, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
