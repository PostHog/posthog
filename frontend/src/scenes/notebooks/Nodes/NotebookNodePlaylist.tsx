import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FilterType, NotebookNodeType, RecordingFilters } from '~/types'
import { SessionRecordingsPlaylistProps } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import {
    addedAdvancedFilters,
    getDefaultFilters,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'
import { fromParamsGivenUrl } from 'lib/utils'
import { urls } from 'scenes/urls'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { SessionRecordingsFilters } from 'scenes/session-recordings/filters/SessionRecordingsFilters'
import { ErrorBoundary } from '@sentry/react'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'

const Component = (props: NotebookNodeViewProps<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { filters, nodeId } = props.attributes
    const playerKey = `notebook-${nodeId}`

    const recordingPlaylistLogicProps: SessionRecordingsPlaylistProps = useMemo(
        () => ({
            logicKey: playerKey,
            filters,
            updateSearchParams: false,
            autoPlay: false,
            onFiltersChange: (newFilters: RecordingFilters) => {
                props.updateAttributes({
                    filters: newFilters,
                })
            },
        }),
        [playerKey, filters]
    )

    const { expanded } = useValues(notebookNodeLogic)
    const { setActions, insertAfter, insertReplayCommentByTimestamp, setMessageListeners, scrollIntoView } =
        useActions(notebookNodeLogic)

    const logic = sessionRecordingsPlaylistLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording } = useValues(logic)
    const { setSelectedRecordingId } = useActions(logic)

    useEffect(() => {
        setActions(
            activeSessionRecording
                ? [
                      {
                          text: 'Pin replay',
                          onClick: () => {
                              insertAfter({
                                  type: NotebookNodeType.Recording,
                                  attrs: {
                                      id: String(activeSessionRecording.id),
                                  },
                              })
                          },
                      },
                      {
                          text: 'Comment',
                          onClick: () => {
                              if (activeSessionRecording.id) {
                                  insertReplayCommentByTimestamp(0, activeSessionRecording.id)
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
                    sessionRecordingPlayerLogic.findMounted({ playerKey, sessionRecordingId })?.actions.seekToTime(time)
                }, 100)
            },
        })
    }, [])

    if (!expanded) {
        // TODO: this isn't so informative as an empty state. Could we do better?
        return <div className="p-4">{summarizePlaylistFilters(filters, {})} </div>
    }

    return <SessionRecordingsPlaylist {...recordingPlaylistLogicProps} />
}

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePlaylistAttributes>): JSX.Element => {
    const { filters } = attributes
    const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
    const defaultFilters = getDefaultFilters()

    const hasAdvancedFilters = useMemo(() => {
        const defaultFilters = getDefaultFilters()
        return addedAdvancedFilters(filters, defaultFilters)
    }, [filters])

    return (
        <ErrorBoundary>
            <SessionRecordingsFilters
                filters={{ ...defaultFilters, ...filters }}
                setFilters={(filters) => updateAttributes({ filters })}
                showPropertyFilters
                onReset={() => updateAttributes({ filters: undefined })}
                hasAdvancedFilters={hasAdvancedFilters}
                showAdvancedFilters={showAdvancedFilters}
                setShowAdvancedFilters={setShowAdvancedFilters}
            />
        </ErrorBoundary>
    )
}

type NotebookNodePlaylistAttributes = {
    filters: RecordingFilters
}

export const NotebookNodePlaylist = createPostHogWidgetNode<NotebookNodePlaylistAttributes>({
    nodeType: NotebookNodeType.RecordingPlaylist,
    defaultTitle: 'Session replays',
    Component,
    heightEstimate: 'calc(100vh - 20rem)',
    href: (attrs) => {
        // TODO: Fix parsing of attrs
        return urls.replay(undefined, attrs.filters)
    },
    resizeable: true,
    startExpanded: true,
    attributes: {
        filters: {
            default: undefined,
        },
    },
    pasteOptions: {
        find: urls.replay() + '(.+)',
        getAttributes: async (match) => {
            const searchParams = fromParamsGivenUrl(match[1].split('?')[1] || '')
            return { filters: searchParams.filters }
        },
    },
    widgets: [
        {
            key: 'settings',
            label: 'Settings',
            Component: Settings,
        },
    ],
})

export function buildPlaylistContent(filters: Partial<FilterType>): JSONContent {
    return {
        type: NotebookNodeType.RecordingPlaylist,
        attrs: { filters },
    }
}
