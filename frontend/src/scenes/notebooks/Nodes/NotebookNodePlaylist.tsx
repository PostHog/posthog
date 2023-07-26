import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType, RecordingFilters } from '~/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { posthogNodePasteRule, useJsonNodeState } from './utils'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { useActions, useValues } from 'kea'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { useRef } from 'react'
import { fromParamsGivenUrl, uuid } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

const HEIGHT = 'calc(100vh - 20rem)'

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

    const logic = sessionRecordingsListLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording, nextSessionRecording } = useValues(logic)
    const { setSelectedRecordingId } = useActions(logic)

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

    return (
        <NodeWrapper
            {...props}
            nodeType={NotebookNodeType.RecordingPlaylist}
            title="Session Replays"
            href={urls.replay(undefined, filters)}
            heightEstimate={HEIGHT}
        >
            <div className="flex flex-row overflow-hidden gap-2 h-full">{content}</div>
        </NodeWrapper>
    )
}

export const NotebookNodePlaylist = Node.create({
    name: NotebookNodeType.RecordingPlaylist,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            height: {
                default: HEIGHT,
            },
            filters: {
                default: undefined,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.RecordingPlaylist,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.RecordingPlaylist, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: urls.replay() + '(.+)',
                type: this.type,
                getAttributes: async (match) => {
                    const searchParams = fromParamsGivenUrl(match[1].split('?')[1] || '')
                    return { filters: searchParams.filters }
                },
            }),
        ]
    },
})
