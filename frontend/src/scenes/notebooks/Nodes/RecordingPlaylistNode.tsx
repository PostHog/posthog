import { mergeAttributes, Node, NodeViewRendererProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'

const Component = ({}: NodeViewRendererProps): JSX.Element => {
    return (
        <NodeWrapper className={NodeType.RecordingPlaylist}>
            <div className="aspect-video">Session Playlist</div>
        </NodeWrapper>
    )
}

export const RecordingPlaylistNode = Node.create({
    name: 'posthogRecordingPlaylist',
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
                tag: NodeType.RecordingPlaylist,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NodeType.RecordingPlaylist, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
