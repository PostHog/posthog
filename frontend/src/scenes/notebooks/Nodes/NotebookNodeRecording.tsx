import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPerson } from '@posthog/icons'
import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { colonDelimitedDuration } from 'lib/utils'
import { parseTimestampToMs } from 'lib/utils/timestamps'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { asDisplay } from 'scenes/persons/person-utils'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { SessionRecordingId } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import { UUID_REGEX_MATCH_GROUPS } from './utils'

const HEIGHT = 500
const MIN_HEIGHT = '20rem'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeRecordingAttributes>): JSX.Element => {
    const { id, noInspector, timestampMs } = attributes

    const recordingLogicProps: SessionRecordingPlayerProps = {
        ...sessionRecordingPlayerProps(id),
        autoPlay: false,
        mode: SessionRecordingPlayerMode.Notebook,
        noBorder: true,
        noInspector: noInspector,
    }

    const { expanded } = useValues(notebookNodeLogic)
    const { setActions, insertAfter, setMessageListeners, setExpanded, scrollIntoView } = useActions(notebookNodeLogic)

    const { sessionPlayerMetaData, sessionPlayerMetaDataLoading, sessionPlayerData } = useValues(
        sessionRecordingDataCoordinatorLogic(recordingLogicProps)
    )
    const { loadRecordingMeta, loadSnapshots } = useActions(sessionRecordingDataCoordinatorLogic(recordingLogicProps))
    const { seekToTimestamp, seekToTime, setPlay, setPause } = useActions(
        sessionRecordingPlayerLogic(recordingLogicProps)
    )

    // TODO Only load data when in view...
    useOnMountEffect(loadRecordingMeta)

    useEffect(() => {
        const person = sessionPlayerMetaData?.person
        setActions([
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
    }, [sessionPlayerMetaData?.person?.id]) // oxlint-disable-line exhaustive-deps

    useOnMountEffect(() => {
        setMessageListeners({
            'play-replay': ({ time }) => {
                if (!expanded) {
                    setExpanded(true)
                }
                setPlay()
                seekToTimestamp(time)
                scrollIntoView()
            },
        })
    })

    // Seek to timestamp when widget is expanded and has a timestamp
    useEffect(() => {
        if (expanded && timestampMs && sessionPlayerData?.start) {
            setPause()
            loadSnapshots()
            seekToTime(timestampMs) // seekToTime only works when sessionPlayerData.start is available
        }
    }, [expanded, timestampMs, sessionPlayerData?.start]) // oxlint-disable-line exhaustive-deps

    if (!sessionPlayerMetaData && !sessionPlayerMetaDataLoading) {
        return <NotFound object="replay" />
    }

    return !expanded ? (
        <div>
            {sessionPlayerMetaData ? (
                <SessionRecordingPreview recording={sessionPlayerMetaData} />
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
            <div className="mt-3">
                <label className="block text-muted mb-1">Start at timestamp</label>
                <LemonInput
                    type="text"
                    fullWidth
                    value={attributes.timestampMs ? colonDelimitedDuration(attributes.timestampMs / 1000) : ''}
                    onBlur={(e) => updateAttributes({ timestampMs: parseTimestampToMs(e.currentTarget.value) })}
                    placeholder="e.g. 00:13:37"
                />
            </div>
        </div>
    )
}

type NotebookNodeRecordingAttributes = {
    id: string
    noInspector: boolean
    timestampMs?: number
}

export const NotebookNodeRecording = createPostHogWidgetNode<NotebookNodeRecordingAttributes>({
    nodeType: NotebookNodeType.Recording,
    titlePlaceholder: 'Session recording',
    Component,
    heightEstimate: HEIGHT,
    minHeight: MIN_HEIGHT,
    href: (attrs) =>
        attrs.timestampMs
            ? `${urls.replaySingle(attrs.id)}?t=${Math.floor(attrs.timestampMs / 1000)}`
            : urls.replaySingle(attrs.id),
    resizeable: true,
    attributes: {
        id: {
            default: null,
        },
        noInspector: {
            default: false,
        },
        timestampMs: {
            default: undefined,
        },
    },
    pasteOptions: {
        find: urls.replaySingle(UUID_REGEX_MATCH_GROUPS),
        getAttributes: async (match) => {
            const id = match[1]
            const remainder = match[2] || ''
            const tMatch = /[?&#]t=(\d+)/.exec(remainder)
            const timestampMs = tMatch ? Number(tMatch[1]) * 1000 : undefined
            return { id, noInspector: false, timestampMs }
        },
    },
    Settings,
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
