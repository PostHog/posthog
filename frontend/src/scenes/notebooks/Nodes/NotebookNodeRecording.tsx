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
import { LemonSwitch } from '@posthog/lemon-ui'
import { IconSettings } from 'lib/lemon-ui/icons'
import { JSONContent, NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'

const HEIGHT = 500
const MIN_HEIGHT = 400

const Component = (props: NotebookNodeViewProps<NotebookNodeRecordingAttributes>): JSX.Element => {
    const id = props.attributes.id
    const noInspector: boolean = props.attributes.noInspector

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

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeRecordingAttributes>): JSX.Element => {
    return (
        <div className="p-3">
            <LemonSwitch
                onChange={() => updateAttributes({ noInspector: !attributes.noInspector })}
                label="Hide Inspector"
                checked={attributes.noInspector}
                fullWidth={true}
            />
        </div>
    )
}

type NotebookNodeRecordingAttributes = {
    id: string
    noInspector: boolean
}

export const NotebookNodeRecording = createPostHogWidgetNode<NotebookNodeRecordingAttributes>({
    nodeType: NotebookNodeType.Recording,
    title: 'Session replay',
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
        find: urls.replaySingle('(.+)'),
        getAttributes: async (match) => {
            return { id: match[1], noInspector: false }
        },
    },
    widgets: [
        {
            key: 'settings',
            label: 'Settings',
            icon: <IconSettings />,
            Component: Settings,
        },
    ],
    serializedText: (attrs) => {
        return attrs.id
    },
})

export function sessionRecordingPlayerProps(id: SessionRecordingId): SessionRecordingPlayerProps {
    return {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
    }
}

export function buildRecordingContent(sessionRecordingId: string): JSONContent {
    return {
        type: 'ph-recording',
        attrs: {
            id: sessionRecordingId,
        },
    }
}
