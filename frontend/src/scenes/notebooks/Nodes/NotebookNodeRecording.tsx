import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { urls } from 'scenes/urls'

const Component = (props: NodeViewProps): JSX.Element => {
    const recordingLogicProps: SessionRecordingPlayerProps = {
        embedded: true,
        sessionRecordingId: props.node.attrs.sessionRecordingId,
        playerKey: `notebook-${props.node.attrs.sessionRecordingId}`,
    }

    return (
        <NodeWrapper
            {...props}
            className={NotebookNodeType.Recording}
            title="Recording"
            href={urls.sessionRecording(recordingLogicProps.sessionRecordingId)}
            // TODO: Fix "meta" preview
            // preview={<PlayerMeta {...recordingLogicProps} />}
        >
            <div className="max-h-120">
                <SessionRecordingPlayer {...recordingLogicProps} />
            </div>
        </NodeWrapper>
    )
}

export const NotebookNodeRecording = Node.create({
    name: NotebookNodeType.Recording,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            sessionRecordingId: {
                default: null,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Recording,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Recording, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
