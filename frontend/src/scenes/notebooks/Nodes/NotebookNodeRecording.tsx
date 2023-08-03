import { NodeViewProps } from '@tiptap/core'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, SessionRecordingId } from '~/types'
import { urls } from 'scenes/urls'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { useEffect } from 'react'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { notebookNodeLogic } from './notebookNodeLogic'

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
    const { expanded } = useValues(notebookNodeLogic)

    useEffect(() => {
        loadRecordingMeta()
    }, [])
    // TODO Only load data when in view...

    return !expanded ? (
        <div>
            {sessionPlayerMetaData ? (
                <SessionRecordingPreview recording={sessionPlayerMetaData} recordingPropertiesLoading={false} />
            ) : (
                <SessionRecordingPreviewSkeleton />
            )}
        </div>
    ) : (
        <SessionRecordingPlayer {...recordingLogicProps} />
    )
}

export const NotebookNodeRecording = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Recording,
    title: 'Session Replay',
    Component,
    heightEstimate: HEIGHT,
    minHeight: MIN_HEIGHT,
    href: (attrs) => urls.replaySingle(attrs.id),
    resizeable: true,
    attributes: {
        id: {
            default: null,
        },
    },
    pasteOptions: {
        find: urls.replaySingle('(.+)'),
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
})

export function sessionRecordingPlayerProps(id: SessionRecordingId): SessionRecordingPlayerProps {
    return {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
    }
}
