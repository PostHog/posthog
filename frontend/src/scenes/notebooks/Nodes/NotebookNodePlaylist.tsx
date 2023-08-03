import { NodeViewProps } from '@tiptap/core'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, RecordingFilters } from '~/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { useJsonNodeState } from './utils'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { useActions, useValues } from 'kea'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { useRef } from 'react'
import { fromParamsGivenUrl, uuid } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = (props: NodeViewProps): JSX.Element => {
    const [filters, setFilters] = useJsonNodeState<RecordingFilters>(props, 'filters')

    const playerKey = useRef(`notebook-${uuid()}`).current

    const recordingPlaylistLogicProps: SessionRecordingsPlaylistProps = {
        filters,
        updateSearchParams: false,
        autoPlay: false,
        mode: 'notebook',
        onFiltersChange: setFilters,
    }

    const { expanded } = useValues(notebookNodeLogic)

    const logic = sessionRecordingsListLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording, nextSessionRecording } = useValues(logic)
    const { setSelectedRecordingId } = useActions(logic)

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
                matching={activeSessionRecording?.matching_events}
                recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                nextSessionRecording={nextSessionRecording}
            />
        </>
    )

    return <div className="flex flex-row overflow-hidden gap-2 h-full">{content}</div>
}

export const NotebookNodePlaylist = createPostHogWidgetNode({
    nodeType: NotebookNodeType.RecordingPlaylist,
    title: 'Session Replays',
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
        getAttributes: (match) => {
            const searchParams = fromParamsGivenUrl(match[1].split('?')[1] || '')
            return { filters: searchParams.filters }
        },
    },
})
