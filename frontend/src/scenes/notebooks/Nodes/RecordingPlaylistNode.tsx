import { mergeAttributes, Node, NodeViewRendererProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

const Component = (props: NodeViewRendererProps): JSX.Element => {
    return (
        <NodeWrapper className={NodeType.RecordingPlaylist} title="Playlist">
            <SessionRecordingsPlaylist filters={props.node.attrs.filters} updateSearchParams={false} />
        </NodeWrapper>
    )
}

export const RecordingPlaylistNode = Node.create({
    name: NodeType.RecordingPlaylist,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            filters: {
                default: {},
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
