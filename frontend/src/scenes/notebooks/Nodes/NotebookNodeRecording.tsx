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
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { useEffect } from 'react'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'

const HEIGHT = 500
const MIN_HEIGHT = 400

const Component = (props: NodeViewProps): JSX.Element => {
    const id = props.node.attrs.id

    const recordingLogicProps: SessionRecordingPlayerProps = {
        ...sessionRecordingPlayerProps(id),
        autoPlay: false,
        mode: SessionRecordingPlayerMode.Notebook,
        noBorder: true,
    }

    const { sessionPlayerMetaData } = useValues(sessionRecordingDataLogic(recordingLogicProps))
    const { loadRecordingMeta } = useActions(sessionRecordingDataLogic(recordingLogicProps))

    useEffect(() => {
        loadRecordingMeta()
    }, [])
    // TODO Only load data when in view...

    return (
        <NodeWrapper
            {...props}
            nodeType={NotebookNodeType.Recording}
            title="Recording"
            href={urls.replaySingle(recordingLogicProps.sessionRecordingId)}
            heightEstimate={HEIGHT}
            minHeight={MIN_HEIGHT}
            resizeable={props.selected}
        >
            {!props.selected ? (
                <div>
                    {sessionPlayerMetaData ? (
                        <SessionRecordingPreview recording={sessionPlayerMetaData} recordingPropertiesLoading={false} />
                    ) : (
                        <SessionRecordingPreviewSkeleton />
                    )}
                </div>
            ) : (
                <SessionRecordingPlayer {...recordingLogicProps} />
            )}
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
            height: {
                default: HEIGHT,
            },
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
