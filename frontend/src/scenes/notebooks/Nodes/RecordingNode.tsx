import { mergeAttributes, Node } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

interface ComponentProps {
    sessionRecordingId: string
}

const Component = ({ sessionRecordingId }: ComponentProps): JSX.Element => {
    return (
        <SessionRecordingPlayer sessionRecordingId={sessionRecordingId} playerKey={`notebook-${sessionRecordingId}`} />
    )
}

export default Node.create({
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
                tag: 'ph-recording',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return ['ph-insight', mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
