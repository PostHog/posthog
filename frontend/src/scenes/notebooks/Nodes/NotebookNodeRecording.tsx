import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, SessionRecordingId } from '~/types'
import { urls } from 'scenes/urls'
import {
    SessionRecordingPlayerMode,
    getCurrentPlayerTime,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { useEffect } from 'react'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { notebookNodeLogic } from './notebookNodeLogic'
import { LemonSwitch } from '@posthog/lemon-ui'
import { JSONContent, NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { asDisplay } from 'scenes/persons/person-utils'
import { IconComment, IconPerson } from 'lib/lemon-ui/icons'

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

    const { expanded } = useValues(notebookNodeLogic)
    const {
        setActions,
        insertAfter,
        insertReplayCommentByTimestamp,
        setMessageListeners,
        setExpanded,
        scrollIntoView,
    } = useActions(notebookNodeLogic)

    const { sessionPlayerMetaData } = useValues(sessionRecordingDataLogic(recordingLogicProps))
    const { loadRecordingMeta } = useActions(sessionRecordingDataLogic(recordingLogicProps))
    const { seekToTime, setPlay } = useActions(sessionRecordingPlayerLogic(recordingLogicProps))

    useEffect(() => {
        loadRecordingMeta()
    }, [])
    // TODO Only load data when in view...

    useEffect(() => {
        const person = sessionPlayerMetaData?.person
        setActions([
            {
                text: 'Comment',
                icon: <IconComment />,
                onClick: () => {
                    const time = getCurrentPlayerTime(recordingLogicProps) * 1000

                    insertReplayCommentByTimestamp(time, id)
                },
            },
            person
                ? {
                      text: `View ${asDisplay(person)}`,
                      icon: <IconPerson />,
                      onClick: () => {
                          insertAfter({
                              type: NotebookNodeType.Person,
                              attrs: {
                                  id: String(person.distinct_ids[0]),
                              },
                          })
                      },
                  }
                : undefined,
        ])
    }, [sessionPlayerMetaData?.person?.id])

    useEffect(() => {
        setMessageListeners({
            'play-replay': ({ time }) => {
                if (!expanded) {
                    setExpanded(true)
                }
                setPlay()

                seekToTime(time)
                scrollIntoView()
            },
        })
    }, [])

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
    defaultTitle: 'Session replay',
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
