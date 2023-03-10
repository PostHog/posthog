import { mergeAttributes, Node, NodeViewRendererProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylist,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { SessionRecordingsPlaylistFilters } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistFilters'

export const PLAYLIST_PREVIEW_RECORDINGS_LIMIT = 5

const Component = (props: NodeViewRendererProps): JSX.Element => {
    const recordingPlaylistLogicProps = {
        embedded: true,
        filters: props.node.attrs.filters,
        updateSearchParams: false,
    }

    return (
        <NodeWrapper
            className={NodeType.RecordingPlaylist}
            title="Playlist"
            edit={<SessionRecordingsPlaylistFilters {...recordingPlaylistLogicProps} />}
            preview={<RecordingsLists {...recordingPlaylistLogicProps} />}
        >
            {/* TODO: replace hardcoded height, 32 (top) + 500 (player) + 16 (margins) + 88 (seekbar) = 620 */}
            <div style={{ maxHeight: 636 }}>
                <SessionRecordingsPlaylist {...recordingPlaylistLogicProps} />
            </div>
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
