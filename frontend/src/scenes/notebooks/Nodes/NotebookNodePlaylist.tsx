import { BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'
import { PostHogErrorBoundary } from '@posthog/react'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { defineNotebookWidgetViews, getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { RecordingsUniversalFiltersEmbed } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import type { sessionRecordingPlayerLogicType } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import {
    asUniversalFilters,
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingsPlaylistSceneLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistSceneLogic'
import { urls } from 'scenes/urls'

import { FilterType, RecordingUniversalFilters } from '~/types'

import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element => {
    if (attributes.id) {
        return <SavedPlaylistDetail attributes={attributes} updateAttributes={updateAttributes} />
    }

    return <PlaylistContent attributes={attributes} updateAttributes={updateAttributes} />
}

const PlaylistContent = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { pinned, nodeId, universalFilters } = attributes
    const playerKey = `notebook-${nodeId}`
    const { personUUIDFromCanvasOverride } = useValues(notebookLogic)

    const recordingPlaylistLogicProps: SessionRecordingPlaylistLogicProps = useMemo(
        () => ({
            logicKey: playerKey,
            filters: universalFilters,
            ...(personUUIDFromCanvasOverride ? { personUUID: personUUIDFromCanvasOverride } : {}),
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

    const { setActions, insertAfter, setMessageListeners } = useActions(notebookNodeLogic)

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

                setTimeout(() => {
                    // NOTE: This is a hack but we need a delay to give time for the player to mount
                    getReplayLogic(sessionRecordingId)?.actions.seekToTime(time)
                }, 100)
            },
        })
    })

    return <SessionRecordingsPlaylist {...recordingPlaylistLogicProps} />
}

function SavedPlaylistDetail(props: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element {
    const { id } = props.attributes
    const logic = sessionRecordingsPlaylistSceneLogic({ shortId: id || 'new' })
    const { filters, pinnedRecordings, playlist, playlistLoading } = useValues(logic)
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(playlist?.name || playlist?.derived_name || 'Recording playlist')
        setTitleStatus(
            playlist?.type
                ? { label: playlist.type === 'collection' ? 'Collection' : 'Saved filter', type: 'default' }
                : null
        )
    }, [playlist, setTitlePlaceholder, setTitleStatus])

    if (!playlist && !playlistLoading) {
        return <NotFound object="recording playlist" />
    }
    if (!playlist || !filters) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }

    return (
        <PlaylistContent
            {...props}
            attributes={{
                ...props.attributes,
                id: undefined,
                universalFilters: asUniversalFilters(filters) || DEFAULT_RECORDING_FILTERS,
                pinned: pinnedRecordings?.map((recording) => String(recording.id)),
            }}
        />
    )
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
    id?: string
    view?: string
    universalFilters: RecordingUniversalFilters
    pinned?: string[]
}

function PlaylistSummary({ attributes }: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element {
    if (!attributes.id) {
        return (
            <div className="flex items-center gap-2 p-3">
                <span className="flex-1">Ad hoc recording playlist</span>
                <LemonTag type="muted">Unsaved</LemonTag>
            </div>
        )
    }

    return <SavedPlaylistSummary id={attributes.id} />
}

function SavedPlaylistSummary({ id }: { id: string }): JSX.Element {
    const logic = sessionRecordingsPlaylistSceneLogic({ shortId: id })
    const { derivedName, playlist, playlistLoading } = useValues(logic)
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(playlist?.name || playlist?.derived_name || 'Recording playlist')
        setTitleStatus(
            playlist?.type
                ? { label: playlist.type === 'collection' ? 'Collection' : 'Saved filter', type: 'default' }
                : null
        )
    }, [playlist, setTitlePlaceholder, setTitleStatus])

    if (!playlist && !playlistLoading) {
        return <NotFound object="recording playlist" />
    }
    if (!playlist) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }

    const recordingCount =
        playlist.type === 'collection'
            ? playlist.recordings_counts?.collection?.count || 0
            : playlist.recordings_counts?.saved_filters?.count || 0

    return (
        <div className="flex flex-wrap items-center gap-2 p-3">
            <span className="min-w-48 flex-1 truncate">{playlist.description || derivedName}</span>
            <span className="text-xs text-secondary">
                {recordingCount} {recordingCount === 1 ? 'recording' : 'recordings'}
            </span>
        </div>
    )
}

function PlaylistConditions({ attributes }: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element {
    if (!attributes.id) {
        return <Settings attributes={attributes} updateAttributes={() => {}} />
    }

    return <SavedPlaylistConditions id={attributes.id} />
}

function SavedPlaylistConditions({ id }: { id: string }): JSX.Element {
    const { playlist, playlistLoading } = useValues(sessionRecordingsPlaylistSceneLogic({ shortId: id }))
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(playlist?.name || playlist?.derived_name || 'Recording playlist')
        setTitleStatus(
            playlist?.type
                ? { label: playlist.type === 'collection' ? 'Collection' : 'Saved filter', type: 'default' }
                : null
        )
    }, [playlist, setTitlePlaceholder, setTitleStatus])

    if (!playlist && !playlistLoading) {
        return <NotFound object="recording playlist" />
    }

    if (!playlist || playlistLoading) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }

    return (
        <Settings
            attributes={{
                nodeId: `playlist-${id}-conditions`,
                universalFilters: asUniversalFilters(playlist.filters) || DEFAULT_RECORDING_FILTERS,
            }}
            updateAttributes={() => {}}
        />
    )
}

const PLAYLIST_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<NotebookNodePlaylistAttributes, 'RecordingPlaylist'>(
    'RecordingPlaylist',
    {
        summary: PlaylistSummary,
        conditions: PlaylistConditions,
    }
)

export const NotebookNodePlaylist = createPostHogWidgetNode<NotebookNodePlaylistAttributes>({
    nodeType: NotebookNodeType.RecordingPlaylist,
    titlePlaceholder: 'Session replays',
    editableTitle: false,
    Component,
    heightEstimate: 'calc(100vh - 20rem)',
    href: (attrs) => {
        return attrs.id ? urls.replayPlaylist(attrs.id) : urls.replay(undefined, attrs.universalFilters)
    },
    resizeable: true,
    expandable: false,
    attributes: {
        id: {},
        view: {},
        universalFilters: {
            default: DEFAULT_RECORDING_FILTERS,
        },
        pinned: {
            default: undefined,
        },
    },
    Settings,
    defaultView: getNotebookWidgetDefaultView('RecordingPlaylist'),
    views: PLAYLIST_NOTEBOOK_WIDGET_VIEWS,
    serializedText: () => 'Recording playlist',
})

export function buildPlaylistContent(filters: Partial<FilterType>): JSONContent {
    return {
        type: NotebookNodeType.RecordingPlaylist,
        attrs: { filters },
    }
}
