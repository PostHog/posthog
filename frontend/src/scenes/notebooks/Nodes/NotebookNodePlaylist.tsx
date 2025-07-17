import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FilterType, NotebookNodeType, RecordingUniversalFilters, ReplayTabs } from '~/types'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    convertLegacyFiltersToUniversalFilters,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { urls } from 'scenes/urls'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingPlayerLogicType } from 'scenes/session-recordings/player/sessionRecordingPlayerLogicType'
import { RecordingsUniversalFiltersEmbed } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { PostHogErrorBoundary } from 'posthog-js/react'
import { IconComment } from '@posthog/icons'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { pinned, nodeId, universalFilters } = attributes
    const playerKey = `notebook-${nodeId}`

    const recordingPlaylistLogicProps: SessionRecordingPlaylistLogicProps = useMemo(
        () => ({
            logicKey: playerKey,
            filters: universalFilters,
            updateSearchParams: false,
            autoPlay: false,
            onFiltersChange: (newFilters) => updateAttributes({ universalFilters: newFilters }),
            pinnedRecordings: pinned,
            onPinnedChange(recording, isPinned) {
                updateAttributes({
                    pinned: isPinned
                        ? [...(pinned || []), String(recording.id)]
                        : pinned?.filter((id) => id !== recording.id),
                })
            },
        }),
        [playerKey, universalFilters, pinned]
    )

    const { setActions, insertAfter, insertReplayCommentByTimestamp, setMessageListeners, scrollIntoView } =
        useActions(notebookNodeLogic)

    const logic = sessionRecordingsPlaylistLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording } = useValues(logic)
    const { setSelectedRecordingId } = useActions(logic)

    const getReplayLogic = (
        sessionRecordingId?: string
    ): BuiltLogic<sessionRecordingPlayerLogicType> | null | undefined =>
        sessionRecordingId ? sessionRecordingPlayerLogic.findMounted({ playerKey, sessionRecordingId }) : null

    useEffect(() => {
        setActions(
            activeSessionRecording
                ? [
                      {
                          text: 'View replay',
                          onClick: () => {
                              getReplayLogic(activeSessionRecording.id)?.actions.setPause()

                              insertAfter({
                                  type: NotebookNodeType.Recording,
                                  attrs: {
                                      id: String(activeSessionRecording.id),
                                      __init: {
                                          expanded: true,
                                      },
                                  },
                              })
                          },
                      },
                      {
                          text: 'Comment',
                          icon: <IconComment />,
                          onClick: () => {
                              if (activeSessionRecording.id) {
                                  const time = getReplayLogic(activeSessionRecording.id)?.values.currentPlayerTime
                                  insertReplayCommentByTimestamp(time ?? 0, activeSessionRecording.id)
                              }
                          },
                      },
                  ]
                : []
        )
    }, [activeSessionRecording])

    useEffect(() => {
        setMessageListeners({
            'play-replay': ({ sessionRecordingId, time }) => {
                // IDEA: We could add the desired start time here as a param, which is picked up by the player...
                setSelectedRecordingId(sessionRecordingId)
                scrollIntoView()

                setTimeout(() => {
                    // NOTE: This is a hack but we need a delay to give time for the player to mount
                    getReplayLogic(sessionRecordingId)?.actions.seekToTime(time)
                }, 100)
            },
        })
    }, [])

    return <SessionRecordingsPlaylist {...recordingPlaylistLogicProps} />
}

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { universalFilters: filters } = attributes

    const setFilters = (newFilters: Partial<RecordingUniversalFilters>): void => {
        updateAttributes({ universalFilters: { ...filters, ...newFilters } })
    }

    return (
        <PostHogErrorBoundary>
            <RecordingsUniversalFiltersEmbed filters={filters} setFilters={setFilters} />
        </PostHogErrorBoundary>
    )
}

export type NotebookNodePlaylistAttributes = {
    universalFilters: RecordingUniversalFilters
    pinned?: string[]
}

export const NotebookNodePlaylist = createPostHogWidgetNode<NotebookNodePlaylistAttributes>({
    nodeType: NotebookNodeType.RecordingPlaylist,
    titlePlaceholder: 'Session replays',
    Component,
    heightEstimate: 'calc(100vh - 20rem)',
    href: (attrs) => {
        // TODO: Fix parsing of attrs
        return urls.replay(undefined, attrs.universalFilters)
    },
    resizeable: true,
    expandable: false,
    attributes: {
        universalFilters: {
            default: DEFAULT_RECORDING_FILTERS,
        },
        pinned: {
            default: undefined,
        },
    },
    pasteOptions: {
        find: urls.replay(ReplayTabs.Home) + '(.*)',
        getAttributes: async (match) => {
            const url = new URL(match[0])
            const stringifiedFilters = url.searchParams.get('filters')
            const filters = stringifiedFilters ? JSON.parse(stringifiedFilters) : {}
            const universalFilters = convertLegacyFiltersToUniversalFilters({}, filters)
            return { filters, universalFilters, pinned: [] }
        },
    },
    Settings,
})

export function buildPlaylistContent(filters: Partial<FilterType>): JSONContent {
    return {
        type: NotebookNodeType.RecordingPlaylist,
        attrs: { filters },
    }
}
