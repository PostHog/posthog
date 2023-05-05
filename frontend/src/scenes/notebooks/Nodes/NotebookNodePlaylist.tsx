import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import {
    SessionRecordingsPlaylist,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { useJsonNodeState } from './utils'

const Component = (props: NodeViewProps): JSX.Element => {
    const [filters, setFilters] = useJsonNodeState(props, 'filters')

    const recordingPlaylistLogicProps: SessionRecordingsPlaylistProps = {
        filters,
        updateSearchParams: false,
        autoPlay: false,
        mode: 'notebook',
        onFiltersChange: setFilters,
    }

    return (
        <NodeWrapper
            {...props}
            className={NotebookNodeType.RecordingPlaylist}
            title="Playlist"
            // preview={<RecordingsLists {...recordingPlaylistLogicProps} />}
        >
            {/* TODO: replace hardcoded height, 32 (top) + 500 (player) + 16 (margins) + 88 (seekbar) = 620 */}
            <div style={{ maxHeight: 600 }} contentEditable={false}>
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
