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
    const recordingLogicProps: SessionRecordingPlayerProps = {
        sessionRecordingId: props.node.attrs.sessionRecordingId,
        playerKey: `notebook-${props.node.attrs.sessionRecordingId}`,
        autoPlay: false,
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

    addPasteRules() {
        return [
            nodePasteRule({
                find: createUrlRegex(urls.sessionRecording('') + '(.+)'),
                type: this.type,
                getAttributes: (match) => {
                    return { sessionRecordingId: match[1] }
                },
            }),
        ]
    },
})
