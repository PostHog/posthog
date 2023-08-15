import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, NotebookNodeWidgetSettings, SessionRecordingId } from '~/types'
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
import { LemonSwitch } from '@posthog/lemon-ui'
import { NotebookNodeViewProps } from '../Notebook/utils'

const HEIGHT = 500
const MIN_HEIGHT = 400

const Component = (props: NotebookNodeViewProps<NotebookNodeRecordingAttributes>): JSX.Element => {
    const id = props.node.attrs.id
    const noInspector: boolean = props.node.attrs.noInspector

    const recordingLogicProps: SessionRecordingPlayerProps = {
        ...sessionRecordingPlayerProps(id),
        autoPlay: false,
        mode: SessionRecordingPlayerMode.Notebook,
        noBorder: true,
        noInspector: noInspector,
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

type NotebookNodeRecordingAttributes = {
    id: string
    noInspector: boolean
}

export const NotebookNodeRecording = createPostHogWidgetNode<NotebookNodeRecordingAttributes>({
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
        noInspector: {
            default: false,
        },
    },
    pasteOptions: {
        find: urls.replaySingle('') + '(.+)',
        getAttributes: (match) => {
            return { id: match[1], noInspector: false }
        },
    },
})

export const Settings = ({ attributes, updateAttributes }: NotebookNodeWidgetSettings): JSX.Element => {
    return (
        <LemonSwitch
            onChange={() => updateAttributes({ noInspector: !attributes.noInspector })}
            label="Hide Inspector"
            checked={attributes.noInspector}
            fullWidth={true}
        />
    )
}

export function sessionRecordingPlayerProps(id: SessionRecordingId): SessionRecordingPlayerProps {
    return {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
    }
}
