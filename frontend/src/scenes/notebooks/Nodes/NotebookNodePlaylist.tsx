import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylist,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { SessionRecordingsPlaylistFilters } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistFilters'

const Component = (props: NodeViewProps): JSX.Element => {
    const recordingPlaylistLogicProps: SessionRecordingsPlaylistProps = {
        filters: props.node.attrs.filters,
        updateSearchParams: false,
    }

    return (
        <NodeWrapper
            {...props}
            className={NotebookNodeType.RecordingPlaylist}
            title="Playlist"
            edit={<SessionRecordingsPlaylistFilters {...recordingPlaylistLogicProps} />}
            preview={<RecordingsLists {...recordingPlaylistLogicProps} />}
        >
            {/* TODO: replace hardcoded height, 32 (top) + 500 (player) + 16 (margins) + 88 (seekbar) = 620 */}
            <div style={{ maxHeight: 636 }} contentEditable={false}>
                <SessionRecordingsPlaylist {...recordingPlaylistLogicProps} />
            </div>
        </NodeWrapper>
    )
}

export const NotebookNodePlaylist = Node.create({
    name: NotebookNodeType.RecordingPlaylist,
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
                tag: NotebookNodeType.RecordingPlaylist,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.RecordingPlaylist, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
