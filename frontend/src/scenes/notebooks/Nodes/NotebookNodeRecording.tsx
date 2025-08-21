import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconComment, IconPerson } from '@posthog/icons'
import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { colonDelimitedDuration } from 'lib/utils'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { asDisplay } from 'scenes/persons/person-utils'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import {
    SessionRecordingPlayerMode,
    getCurrentPlayerTime,
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
    const {
        setActions,
        insertAfter,
        insertReplayCommentByTimestamp,
        setMessageListeners,
        setExpanded,
        scrollIntoView,
    } = useActions(notebookNodeLogic)

    const { sessionPlayerMetaData, sessionPlayerMetaDataLoading, sessionPlayerData } = useValues(
        sessionRecordingDataLogic(recordingLogicProps)
    )
    const { loadRecordingMeta, loadSnapshots, loadTargetedSnapshot } = useActions(
        sessionRecordingDataLogic(recordingLogicProps)
    )
    const { seekToTimestamp, setPlay, setPause } = useActions(sessionRecordingPlayerLogic(recordingLogicProps))
    const { isPlaying } = useValues(sessionRecordingPlayerLogic(recordingLogicProps))

    // TODO Only load data when in view...
    useOnMountEffect(loadRecordingMeta)

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

    // Preload snapshots as soon as the widget expands so the player can render a still frame
    useEffect(() => {
        if (expanded) {
            // Ensure we start paused and just show a still frame
            setPause()
            // Use targeted loading if we have a timestamp - this loads only the specific frame needed
            // If no timestamp, fall back to loading all snapshots
            if (timestampMs && sessionPlayerData?.start) {
                const targetTimestamp = sessionPlayerData.start.valueOf() + timestampMs
                loadTargetedSnapshot(targetTimestamp)
            } else {
                loadSnapshots()
            }
        }
    }, [expanded, timestampMs, sessionPlayerData?.start]) // oxlint-disable-line exhaustive-deps

    // Seek to timestamp when widget is expanded and has a timestamp
    useEffect(() => {
        if (expanded && timestampMs && sessionPlayerData?.start) {
            // Convert relative ms to absolute recording timestamp and seek (paused)
            setPause()
            const desired = sessionPlayerData.start.valueOf() + timestampMs
            seekToTimestamp(desired)
        }
    }, [expanded, timestampMs, sessionPlayerData?.start]) // oxlint-disable-line exhaustive-deps

    // When user starts playing, ensure we have all snapshots loaded (not just the target frame)
    useEffect(() => {
        if (isPlaying && expanded && timestampMs) {
            // User is actually playing and we initially loaded with a target timestamp
            // Load all snapshots for smooth playback (without target timestamp)
            loadSnapshots()
        }
    }, [isPlaying, expanded, timestampMs]) // oxlint-disable-line exhaustive-deps

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
            const tMatch = /[?&#]t=([^&]+)/.exec(remainder)
            const timestampMs = tMatch ? parseTimestampToMs(decodeURIComponent(tMatch[1])) : undefined
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

export function buildRecordingContent(sessionRecordingId: string): JSONContent {
    return {
        type: 'ph-recording',
        attrs: {
            id: sessionRecordingId,
        },
    }
}

// Utilities: parse and format timestamps like "54s", "1:23", "00:01:23"
function parseTimestampToMs(input?: string | null): number | undefined {
    if (!input) {
        return undefined
    }
    const value = String(input).trim()
    if (!value) {
        return undefined
    }
    // mm:ss or hh:mm:ss
    const parts = value.split(':').map((p) => parseInt(p, 10))
    if (parts.every((n) => !Number.isNaN(n))) {
        let seconds = 0
        if (parts.length === 2) {
            const [mm, ss] = parts
            seconds = mm * 60 + ss
        } else if (parts.length === 3) {
            const [hh, mm, ss] = parts
            seconds = hh * 3600 + mm * 60 + ss
        }
        if (seconds > 0) {
            return seconds * 1000
        }
    }
    return undefined
}
