import { mergeAttributes, Node, NodeViewRendererProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'

interface ComponentProps extends NodeViewRendererProps {
    sessionRecordingId: string
}

const Component = (props: ComponentProps): JSX.Element => {
    return (
        <NodeWrapper className={NodeType.Recording}>
            <div className="aspect-square">
                <SessionRecordingPlayer
                    noBorder
                    sessionRecordingId={props.node.attrs.sessionRecordingId}
                    playerKey={`notebook-${props.node.attrs.sessionRecordingId}`}
                />
            </div>
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
            sessionRecordingId: {
                default: null,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NodeType.Recording,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NodeType.Recording, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
