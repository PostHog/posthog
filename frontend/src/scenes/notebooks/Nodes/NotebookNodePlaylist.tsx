import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FilterType, NotebookNodeType, RecordingFilters } from '~/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import {
    addedAdvancedFilters,
    getDefaultFilters,
    sessionRecordingsListLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { useActions, useValues } from 'kea'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { useEffect, useMemo, useState } from 'react'
import { fromParamsGivenUrl } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { SessionRecordingsFilters } from 'scenes/session-recordings/filters/SessionRecordingsFilters'
import { ErrorBoundary } from '@sentry/react'

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
    const { setActions, insertAfter } = useActions(notebookNodeLogic)

    const logic = sessionRecordingsListLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording, nextSessionRecording, matchingEventsMatchType } = useValues(logic)
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
                  ]
                : []
        )
    }, [activeSessionRecording])

    if (!expanded) {
        return <div className="p-4">20+ recordings </div>
    }

    const content = !activeSessionRecording?.id ? (
        <RecordingsLists {...recordingPlaylistLogicProps} />
    ) : (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronLeft />}
                onClick={() => setSelectedRecordingId(null)}
                className="self-start"
            />
            <SessionRecordingPlayer
                playerKey={playerKey}
                sessionRecordingId={activeSessionRecording.id}
                recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                nextSessionRecording={nextSessionRecording}
                matchingEventsMatchType={matchingEventsMatchType}
            />
        </>
    )

    return <div className="flex flex-row overflow-hidden gap-2 h-full">{content}</div>
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
