import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, SessionRecordingId } from '~/types'
import { urls } from 'scenes/urls'
import { posthogNodePasteRule } from './utils'
import { uuid } from 'lib/utils'

const HEIGHT = 500

const Component = (props: NodeViewProps): JSX.Element => {
    const id = props.node.attrs.id

    const recordingLogicProps = {
        ...sessionRecordingPlayerProps(id),
        autoPlay: false,
    }

    return (
        <NodeWrapper
            {...props}
            nodeType={NotebookNodeType.Recording}
            title="Recording"
            href={urls.replaySingle(recordingLogicProps.sessionRecordingId)}
            heightEstimate={HEIGHT}
        >
            <div style={{ height: HEIGHT }}>
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
            nodeId: { default: uuid() },
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
            posthogNodePasteRule({
                find: urls.replaySingle('') + '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})

export function sessionRecordingPlayerProps(id: SessionRecordingId): SessionRecordingPlayerProps {
    return {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
    }
}
