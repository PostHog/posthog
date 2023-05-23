import { mergeAttributes, Node, nodePasteRule, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { urls } from 'scenes/urls'
import { createUrlRegex } from './utils'

const Component = (props: NodeViewProps): JSX.Element => {
    const id = props.node.attrs.id
    const recordingLogicProps: SessionRecordingPlayerProps = {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
        autoPlay: false,
    }

    return (
        <NodeWrapper
            {...props}
            className={NotebookNodeType.Recording}
            title="Recording"
            href={urls.replaySingle(recordingLogicProps.sessionRecordingId)}
            // TODO: Fix "meta" preview
            // preview={<PlayerMeta {...recordingLogicProps} />}
        >
            <div style={{ height: 500 }}>
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
            id: {
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

    addPasteRules() {
        return [
            nodePasteRule({
                find: createUrlRegex(urls.replaySingle('') + '(.+)'),
                type: this.type,
                getAttributes: (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
