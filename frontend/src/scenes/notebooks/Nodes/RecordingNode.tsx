import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { PlayerMeta } from 'scenes/session-recordings/player/PlayerMeta'

const Component = (props: NodeViewProps): JSX.Element => {
    const recordingLogicProps = {
        embedded: true,
        sessionRecordingId: props.node.attrs.sessionRecordingId,
        playerKey: `notebook-${props.node.attrs.sessionRecordingId}`,
    }

    return (
        <NodeWrapper
            {...props}
            className={NodeType.Recording}
            title="Recording"
            preview={<PlayerMeta {...recordingLogicProps} />}
        >
            {/* TODO: replace hardcoded height, 32 (top) + 500 (player) + 16 (margins) + 88 (seekbar) = 620 */}
            <div style={{ maxHeight: 636 }}>
                <SessionRecordingPlayer {...recordingLogicProps} />
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
