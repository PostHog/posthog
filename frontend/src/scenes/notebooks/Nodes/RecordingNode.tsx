import { mergeAttributes, Node, NodeViewRendererProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'

const Component = (props: NodeViewRendererProps): JSX.Element => {
    return (
        <NodeWrapper className={NodeType.Recording} title="Recording">
            <div className="aspect-square">
                <SessionRecordingPlayer
                    embedded
                    sessionRecordingId={props.node.attrs.sessionRecordingId}
                    playerKey={`notebook-${props.node.attrs.sessionRecordingId}`}
                />
            </div>
        </NodeWrapper>
    )
}

export const RecordingNode = Node.create({
    name: NodeType.Recording,
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
