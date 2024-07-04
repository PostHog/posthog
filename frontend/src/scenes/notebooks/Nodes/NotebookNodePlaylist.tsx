import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FilterType, NotebookNodeType, RecordingFilters, RecordingUniversalFilters, ReplayTabs } from '~/types'
import {
    DEFAULT_SIMPLE_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    convertLegacyFiltersToUniversalFilters,
    getDefaultFilters,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { urls } from 'scenes/urls'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { SessionRecordingsFilters } from 'scenes/session-recordings/filters/SessionRecordingsFilters'
import { ErrorBoundary } from '@sentry/react'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { IconComment } from 'lib/lemon-ui/icons'
import { sessionRecordingPlayerLogicType } from 'scenes/session-recordings/player/sessionRecordingPlayerLogicType'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { RecordingsUniversalFilters } from 'scenes/session-recordings/filters/RecordingsUniversalFilters'

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { filters, simpleFilters, pinned, nodeId, universalFilters } = attributes
    const playerKey = `notebook-${nodeId}`

    const recordingPlaylistLogicProps: SessionRecordingPlaylistLogicProps = useMemo(
        () => ({
            logicKey: playerKey,
            advancedFilters: filters,
            simpleFilters,
            universalFilters,
            updateSearchParams: false,
            autoPlay: false,
            onFiltersChange: (newFilters, legacyFilters) => {
                updateAttributes({ universalFilters: newFilters, filters: legacyFilters })
            },
            pinnedRecordings: pinned,
            onPinnedChange(recording, isPinned) {
                updateAttributes({
                    pinned: isPinned
                        ? [...(pinned || []), String(recording.id)]
                        : pinned?.filter((id) => id !== recording.id),
                })
            },
        }),
        [playerKey, filters, pinned]
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
    const { filters, simpleFilters, universalFilters } = attributes
    const defaultFilters = getDefaultFilters()
    const hasUniversalFiltering = useFeatureFlag('SESSION_REPLAY_UNIVERSAL_FILTERS')

    const setUniversalFilters = (filters: Partial<RecordingUniversalFilters>): void => {
        updateAttributes({ universalFilters: { ...universalFilters, ...filters } })
    }

    return (
        <ErrorBoundary>
            {hasUniversalFiltering ? (
                <RecordingsUniversalFilters filters={universalFilters} setFilters={setUniversalFilters} />
            ) : (
                <SessionRecordingsFilters
                    advancedFilters={{ ...defaultFilters, ...filters }}
                    simpleFilters={simpleFilters ?? DEFAULT_SIMPLE_RECORDING_FILTERS}
                    setAdvancedFilters={(filters) => updateAttributes({ filters })}
                    setSimpleFilters={(simpleFilters) => updateAttributes({ simpleFilters })}
                    showPropertyFilters
                    onReset={() =>
                        updateAttributes({ filters: defaultFilters, simpleFilters: DEFAULT_SIMPLE_RECORDING_FILTERS })
                    }
                />
            )}
        </ErrorBoundary>
    )
}

export type NotebookNodePlaylistAttributes = {
    universalFilters: RecordingUniversalFilters
    pinned?: string[]
    // TODO: these filters are now deprecated and will be removed once we rollout universal filters to everyone
    filters: RecordingFilters
    simpleFilters?: RecordingFilters
}

export const NotebookNodePlaylist = createPostHogWidgetNode<NotebookNodePlaylistAttributes>({
    nodeType: NotebookNodeType.RecordingPlaylist,
    titlePlaceholder: 'Session replays',
    Component,
    heightEstimate: 'calc(100vh - 20rem)',
    href: (attrs) => {
        // TODO: Fix parsing of attrs
        return urls.replay(undefined, attrs.filters)
    },
    resizeable: true,
    expandable: false,
    attributes: {
        filters: {
            default: undefined,
        },
        simpleFilters: {
            default: {},
        },
        universalFilters: {
            default: undefined,
        },
        pinned: {
            default: undefined,
        },
    },
    pasteOptions: {
        find: urls.replay(ReplayTabs.Recent) + '(.*)',
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
