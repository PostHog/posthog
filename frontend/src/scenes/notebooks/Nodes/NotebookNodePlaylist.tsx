import { BuiltLogic, useActions, useValues } from 'kea'
import { PostHogErrorBoundary } from 'posthog-js/react'
import { useEffect, useMemo } from 'react'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { RecordingsUniversalFiltersEmbed } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sessionRecordingPlayerLogicType } from 'scenes/session-recordings/player/sessionRecordingPlayerLogicType'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    convertLegacyFiltersToUniversalFilters,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { FilterType, RecordingUniversalFilters, ReplayTabs } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

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
        // oxlint-disable-next-line exhaustive-deps
        [playerKey, universalFilters, pinned]
    )

    const { setActions, insertAfter, setMessageListeners, scrollIntoView } = useActions(notebookNodeLogic)

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
                  ]
                : []
        )
        // oxlint-disable-next-line exhaustive-deps
    }, [activeSessionRecording])

    useOnMountEffect(() => {
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
    })

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
